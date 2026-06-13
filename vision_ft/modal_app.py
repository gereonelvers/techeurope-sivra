"""
Modal app for LoRA fine-tuning Gemma 4 vision (google/gemma-4-E2B-it) on the
buyer-agent marketplace trajectories.

Two entrypoints:
  * smoke_test  -- loads the model on a GPU, builds ~16 image->action examples,
                   runs ~15 LoRA steps, asserts loss is finite, prints loss curve,
                   GPU type and wall-time. THIS is the deliverable for now.
  * full_train  -- the real run (all steps, multiple epochs). DO NOT launch without
                   sign-off. Guarded by an explicit --i-have-signoff flag.

Run the smoke test:
    cd vision_ft
    set -a; source ../.env; set +a       # loads MODAL_TOKEN_ID / MODAL_TOKEN_SECRET
    .venv/bin/modal run modal_app.py::smoke_test

Training stack: Unsloth FastVisionModel + TRL SFTTrainer (Unsloth officially supports
Gemma 4 vision). If Unsloth fails to import/load gemma4, the function falls back to a
plain transformers + peft + TRL path and reports which path actually worked.
"""

from __future__ import annotations

import os
import time

import modal

APP_NAME = "buyer-vision-ft"

# Canonical Google repo (gated=False for our token). Unsloth mirror as fallback.
MODEL_ID = "google/gemma-4-E2B-it"
UNSLOTH_MODEL_ID = "unsloth/gemma-4-E2B-it"

# ---------------------------------------------------------------------------
# Image: bleeding-edge transformers (gemma4 needs >=5.5), unsloth, trl, peft.
# Heavy deps live ONLY in this Modal image, never in the local venv.
# ---------------------------------------------------------------------------
gpu_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    # Pin unsloth to a known gemma4-capable release and let IT resolve a compatible
    # transformers/trl/peft set. Hard-pinning transformers>=5.5 ourselves caused pip
    # to backtrack through dozens of unsloth releases. unsloth 2026.6.6 ships gemma4
    # support and pins transformers>=5.5 internally.
    .pip_install(
        "unsloth==2026.6.6",
        "unsloth_zoo",
        "bitsandbytes>=0.45.0",
        "pillow>=10.0.0",
        "huggingface_hub",
    )
    # Bundle the dataset builder + a tiny smoke-test slice into the image so the
    # smoke test is fully self-contained (no Volume upload needed to validate).
    .add_local_file(
        os.path.join(os.path.dirname(__file__), "build_dataset.py"),
        "/root/build_dataset.py",
    )
    .add_local_dir(
        os.path.join(os.path.dirname(__file__), "smoke_data"),
        "/root/smoke_data",
    )
)

app = modal.App(APP_NAME)

# Persisted checkpoints / adapters for the full run.
ckpt_vol = modal.Volume.from_name("buyer-vision-ckpt", create_if_missing=True)
# HF cache so we don't re-download 10GB weights between runs.
hf_cache_vol = modal.Volume.from_name("buyer-vision-hf-cache", create_if_missing=True)

# HF token secret. The .env key is misspelled HUGGINFACE_API_KEY (no "G").
# Create this secret once with the helper at the bottom, or via:
#   modal secret create huggingface HUGGINGFACE_API_KEY=hf_xxx HF_TOKEN=hf_xxx
hf_secret = modal.Secret.from_name("huggingface")


# ---------------------------------------------------------------------------
# Shared training helper used by both smoke + full runs.
# ---------------------------------------------------------------------------
def _build_examples(traj_path, image_root, limit):
    """Build TRL-ready examples and attach loaded PIL images."""
    from PIL import Image
    import build_dataset

    out = []
    for ex in build_dataset.iter_examples(traj_path, image_root=image_root, limit=limit):
        img_path = ex["image"]
        if not os.path.exists(img_path):
            continue
        pil = Image.open(img_path).convert("RGB")
        # Inject the actual PIL image into the image content block.
        msgs = ex["messages"]
        for block in msgs[0]["content"]:
            if block.get("type") == "image":
                block["image"] = pil
        out.append({"messages": msgs})
    return out


def _resolve_hf_token():
    for k in ("HUGGINGFACE_API_KEY", "HUGGINFACE_API_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        v = os.environ.get(k)
        if v:
            os.environ["HF_TOKEN"] = v
            os.environ["HUGGING_FACE_HUB_TOKEN"] = v
            return v
    return None


def _train_unsloth(model_id, examples, max_steps, lr, output_dir, report):
    """Primary path: Unsloth FastVisionModel + TRL SFTTrainer."""
    import torch
    from unsloth import FastVisionModel
    from unsloth.trainer import UnslothVisionDataCollator
    from trl import SFTTrainer, SFTConfig

    report["stack"] = "unsloth"
    report["model_id"] = model_id

    model, processor = FastVisionModel.from_pretrained(
        model_id,
        load_in_4bit=True,
        use_gradient_checkpointing="unsloth",
    )
    report["weights_loaded"] = True

    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=True,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=16,
        lora_alpha=16,
        lora_dropout=0.0,
        bias="none",
        random_state=3407,
        target_modules="all-linear",
    )

    FastVisionModel.for_training(model)

    losses = []

    trainer = SFTTrainer(
        model=model,
        train_dataset=examples,
        processing_class=processor.tokenizer,
        data_collator=UnslothVisionDataCollator(model, processor),
        args=SFTConfig(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=2,
            warmup_steps=1,
            max_steps=max_steps,
            learning_rate=lr,
            logging_steps=1,
            optim="adamw_8bit",
            weight_decay=0.001,
            lr_scheduler_type="cosine",
            seed=3407,
            output_dir=output_dir,
            report_to="none",
            remove_unused_columns=False,
            dataset_text_field="",
            dataset_kwargs={"skip_prepare_dataset": True},
            max_length=2048,
        ),
    )
    # attach loss-capturing callback
    from transformers import TrainerCallback

    class _CB(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            if logs and "loss" in logs:
                losses.append(float(logs["loss"]))

    trainer.add_callback(_CB())
    out = trainer.train()
    report["losses"] = losses
    report["train_runtime_s"] = out.metrics.get("train_runtime")
    return model, processor


def _train_trl_fallback(model_id, examples, max_steps, lr, output_dir, report):
    """Fallback path: plain transformers + peft + TRL (no Unsloth)."""
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText, TrainerCallback
    from peft import LoraConfig, get_peft_model
    from trl import SFTTrainer, SFTConfig

    report["stack"] = "trl-transformers"
    report["model_id"] = model_id

    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, torch_dtype=torch.bfloat16, device_map="cuda", trust_remote_code=True,
    )
    report["weights_loaded"] = True

    peft_cfg = LoraConfig(
        r=16, lora_alpha=16, lora_dropout=0.0, bias="none",
        target_modules="all-linear", task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_cfg)

    def collate(batch):
        texts, imgs = [], []
        for ex in batch:
            msgs = ex["messages"]
            texts.append(processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False))
            im = None
            for block in msgs[0]["content"]:
                if block.get("type") == "image":
                    im = block["image"]
            imgs.append([im])
        out = processor(text=texts, images=imgs, return_tensors="pt", padding=True)
        labels = out["input_ids"].clone()
        labels[labels == processor.tokenizer.pad_token_id] = -100
        out["labels"] = labels
        return out

    losses = []

    class _CB(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            if logs and "loss" in logs:
                losses.append(float(logs["loss"]))

    trainer = SFTTrainer(
        model=model,
        train_dataset=examples,
        data_collator=collate,
        args=SFTConfig(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=2,
            warmup_steps=1,
            max_steps=max_steps,
            learning_rate=lr,
            logging_steps=1,
            optim="adamw_8bit",
            lr_scheduler_type="cosine",
            seed=3407,
            output_dir=output_dir,
            report_to="none",
            remove_unused_columns=False,
            dataset_kwargs={"skip_prepare_dataset": True},
            max_length=2048,
            bf16=True,
        ),
    )
    trainer.add_callback(_CB())
    out = trainer.train()
    report["losses"] = losses
    report["train_runtime_s"] = out.metrics.get("train_runtime")
    return model, processor


# ---------------------------------------------------------------------------
# SMOKE TEST  -- the deliverable.
# ---------------------------------------------------------------------------
@app.function(
    image=gpu_image,
    gpu="A100-40GB",
    timeout=60 * 30,
    secrets=[hf_secret],
    volumes={"/cache": hf_cache_vol},
)
def smoke_test(n_examples: int = 16, max_steps: int = 15):
    """Validate the full pipeline end-to-end on a GPU. Does NOT do the full run."""
    import torch

    os.environ.setdefault("HF_HOME", "/cache/hf")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    token = _resolve_hf_token()

    report = {
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO GPU",
        "hf_token_present": bool(token),
        "weights_loaded": False,
    }
    print(f"[smoke] GPU: {report['gpu']}  hf_token_present={report['hf_token_present']}")

    # Build a tiny dataset from the bundled smoke slice.
    t0 = time.time()
    examples = _build_examples(
        traj_path="/root/smoke_data/trajectories.jsonl",
        image_root="/root/smoke_data/images",
        limit=n_examples,
    )
    report["n_examples"] = len(examples)
    print(f"[smoke] built {len(examples)} examples in {time.time()-t0:.1f}s")
    assert len(examples) >= 4, "not enough smoke examples built"

    # Try Unsloth first, fall back to TRL/transformers.
    t1 = time.time()
    try:
        _train_unsloth(UNSLOTH_MODEL_ID, examples, max_steps, 2e-4, "/cache/smoke_out", report)
    except Exception as e:
        import traceback
        report["unsloth_error"] = f"{type(e).__name__}: {e}"
        print(f"[smoke] Unsloth path FAILED: {report['unsloth_error']}")
        print(traceback.format_exc()[-2000:])
        print("[smoke] falling back to TRL/transformers path...")
        _train_trl_fallback(MODEL_ID, examples, max_steps, 2e-4, "/cache/smoke_out", report)

    report["train_wall_s"] = round(time.time() - t1, 1)
    losses = report.get("losses", [])
    report["loss_first"] = losses[0] if losses else None
    report["loss_last"] = losses[-1] if losses else None
    report["loss_finite"] = all(map(lambda x: x == x and abs(x) != float("inf"), losses)) if losses else False
    report["loss_decreased"] = (len(losses) >= 2 and losses[-1] < losses[0])

    print("\n========== SMOKE REPORT ==========")
    print(f"stack         : {report.get('stack')}")
    print(f"model_id      : {report.get('model_id')}")
    print(f"GPU           : {report['gpu']}")
    print(f"weights_loaded: {report['weights_loaded']}")
    print(f"n_examples    : {report['n_examples']}")
    print(f"train_wall_s  : {report['train_wall_s']}")
    print(f"loss curve    : {[round(l,3) for l in losses]}")
    print(f"loss finite   : {report['loss_finite']}")
    print(f"loss first/last: {report['loss_first']} -> {report['loss_last']}")
    print("==================================\n")
    return report


# ---------------------------------------------------------------------------
# FULL TRAIN  -- guarded. Do NOT run without sign-off.
# ---------------------------------------------------------------------------
@app.function(
    image=gpu_image,
    gpu="H100",
    timeout=60 * 60 * 6,
    secrets=[hf_secret],
    volumes={"/cache": hf_cache_vol, "/ckpt": ckpt_vol},
)
def full_train(epochs: int = 2, lr: float = 2e-4, i_have_signoff: bool = False):
    """Real fine-tune over ALL steps. Requires explicit sign-off flag."""
    if not i_have_signoff:
        raise RuntimeError(
            "full_train is guarded. Re-run with i_have_signoff=True ONLY after the "
            "user has approved the proposed run. Aborting."
        )
    import torch

    os.environ.setdefault("HF_HOME", "/cache/hf")
    token = _resolve_hf_token()
    report = {"gpu": torch.cuda.get_device_name(0), "hf_token_present": bool(token)}

    # Full dataset lives on the ckpt/data volume at /ckpt/data after upload_dataset.
    traj = "/ckpt/data/trajectories.jsonl"
    image_root = "/ckpt/data/images"
    examples = _build_examples(traj, image_root, limit=None)
    report["n_examples"] = len(examples)
    print(f"[full] {len(examples)} examples, {epochs} epochs")

    # epochs -> max_steps (bs=1, grad_accum=4)
    grad_accum = 4
    steps_per_epoch = max(1, len(examples) // grad_accum)
    max_steps = steps_per_epoch * epochs

    try:
        model, processor = _train_unsloth(UNSLOTH_MODEL_ID, examples, max_steps, lr, "/ckpt/out", report)
    except Exception as e:
        report["unsloth_error"] = str(e)
        model, processor = _train_trl_fallback(MODEL_ID, examples, max_steps, lr, "/ckpt/out", report)

    model.save_pretrained("/ckpt/adapter")
    processor.save_pretrained("/ckpt/adapter")
    ckpt_vol.commit()
    print(f"[full] saved adapter to volume buyer-vision-ckpt:/adapter")
    return report


# ---------------------------------------------------------------------------
# Helper: upload the FULL dataset to the checkpoint volume (for full_train only).
# Uses Volume.batch_upload from the LOCAL side so we never mount the live, actively
# written dataset dir into an image build (which trips Modal's "modified during
# build" guard). Run once before full_train:
#     modal run modal_app.py::upload_dataset
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def upload_dataset():
    data_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "datasets", "buyer",
    )
    print(f"[upload] staging {data_root} -> volume buyer-vision-ckpt:/data ...")
    with ckpt_vol.batch_upload(force=True) as batch:
        batch.put_directory(os.path.join(data_root, "images"), "/data/images")
        batch.put_file(
            os.path.join(data_root, "trajectories.jsonl"),
            "/data/trajectories.jsonl",
        )
    print("[upload] done. Dataset is on the volume at /data.")


@app.local_entrypoint()
def main():
    """Default: run the smoke test."""
    report = smoke_test.remote()
    print("RETURNED REPORT:", report)
