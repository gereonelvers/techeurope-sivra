"""
Modal serving app for the buyer-agent Gemma 4 vision policy.

This is a NEW, SEPARATE Modal app from `vision_ft/modal_app.py` (which is the
*training* job and must not be touched). It loads the base vision model
`google/gemma-4-E2B-it` and, IF a LoRA adapter has been committed to the Modal
Volume `buyer-vision-ckpt` at `/adapter`, applies it on top. Until the fine-tune
finishes the adapter dir is absent and we serve the BASE model (smoke path).

Input  : a marketplace screenshot (PNG, base64) + a goal string.
Output : the next UI action as a single JSON object constrained to the schema
         used by the training data (see PROMPT below), decoded greedily (temp 0).

Prompt format is byte-compatible with `vision_ft/build_dataset.py` so that, once
the adapter lands, the same endpoint immediately benefits from the fine-tune.

------------------------------------------------------------------------------
Run / smoke (base model, adapter not required):
    cd runtime
    set -a; source ../.env; set +a            # MODAL_TOKEN_ID / MODAL_TOKEN_SECRET
    .venv/bin/modal run serve_modal.py::smoke           # in-container self-test
    .venv/bin/modal deploy serve_modal.py               # deploy the web endpoint

After deploy, the warm web endpoint is at:
    https://<workspace>--buyer-vision-serve-infer.modal.run

Re-point at the trained adapter: nothing to change. The endpoint reads the
volume on container start, so once `full_train` commits the adapter to
`buyer-vision-ckpt:/adapter`, just bounce the app:
    .venv/bin/modal deploy serve_modal.py     # (or stop the app to drop warm containers)
------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import os
import re
import time

import modal

APP_NAME = "buyer-vision-serve"

MODEL_ID = "google/gemma-4-E2B-it"
ADAPTER_DIR = "/adapter"          # where full_train commits the LoRA on the volume
VIEWPORT_W, VIEWPORT_H = 1280, 800

# ---------------------------------------------------------------------------
# EXACT training prompt (mirrors vision_ft/build_dataset.py). Keep byte-identical
# so the fine-tuned adapter sees the distribution it was trained on.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a buyer agent operating a web marketplace through a 1280x800 browser viewport. "
    "You are given a screenshot of the current page and a shopping goal. "
    "Decide the single next UI action that makes progress toward buying the target item, "
    "then selecting Done.\n"
    "Respond with ONLY one JSON object, no prose, using exactly one of these schemas:\n"
    '{"action":"click","x":<int>,"y":<int>}\n'
    '{"action":"type","text":"<string>"}\n'
    '{"action":"scroll","dy":<int>}\n'
    '{"action":"navigate_back"}\n'
    '{"action":"done","item_id":<int>}'
)


def build_user_text(goal: str) -> str:
    """Reproduce vision_ft/build_dataset.py::_user_text for an arbitrary goal."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"GOAL: Find and purchase the best matching item for: {goal}.\n"
        f"Output the next action as JSON."
    )


# ---------------------------------------------------------------------------
# Image: Unsloth (to load the LoRA the way it was TRAINED) + transformers/peft
# (base-model fallback). The adapter committed by vision_ft/full_train was trained
# with Unsloth FastVisionModel against `unsloth/gemma-4-e2b-it-unsloth-bnb-4bit`,
# so its adapter_config targets Unsloth-patched modules (`Gemma4ClippableLinear`).
# Loading it onto the plain `google/gemma-4-E2B-it` via stock peft raises
# `ValueError: Target module Gemma4ClippableLinear ... is not supported`. We
# therefore mirror the training stack: load the Unsloth 4-bit base, then attach
# the adapter. Unsloth pins a gemma4-capable transformers/peft set internally.
# (Matches vision_ft/modal_app.py's `unsloth==2026.6.6`.)
# ---------------------------------------------------------------------------
inference_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "unsloth==2026.6.6",
        "unsloth_zoo",
        "bitsandbytes>=0.45.0",
        # Gemma4Processor (image processing) requires torchvision; without it the
        # processor import raises ModuleNotFoundError("Gemma4Processor").
        "torchvision",
        "pillow>=10.0.0",
        "huggingface_hub",
        "fastapi[standard]",
    )
)

# The Unsloth 4-bit base the adapter was trained against (see adapter_config.json
# base_model_name_or_path). Loading the adapter onto THIS base makes the LoRA
# target modules line up. Falls back to MODEL_ID (plain transformers) if Unsloth
# is unavailable, in which case we serve BASE rather than crash.
UNSLOTH_MODEL_ID = "unsloth/gemma-4-e2b-it-unsloth-bnb-4bit"

app = modal.App(APP_NAME)

# Same volume the training job commits the adapter to (read-only here).
ckpt_vol = modal.Volume.from_name("buyer-vision-ckpt", create_if_missing=True)
# Reuse the training HF cache so we don't re-download ~10GB of weights.
hf_cache_vol = modal.Volume.from_name("buyer-vision-hf-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface")

GPU = "A100-40GB"


def _resolve_hf_token():
    for k in ("HUGGINGFACE_API_KEY", "HUGGINFACE_API_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        v = os.environ.get(k)
        if v:
            os.environ["HF_TOKEN"] = v
            os.environ["HUGGING_FACE_HUB_TOKEN"] = v
            return v
    return None


# Valid action shapes for light schema validation / repair.
_ACTIONS = {"click", "type", "scroll", "navigate_back", "done"}


def _extract_action_json(text: str) -> dict:
    """Pull the first balanced {...} out of the model text and coerce to schema.

    Robust to the base model wrapping the JSON in prose / markdown / repeats.
    Returns a dict guaranteed to have an "action" key (falls back to a no-op
    scroll if nothing parseable is found, so the loop never crashes).
    """
    if not text:
        return {"action": "scroll", "dy": 200, "_repair": "empty"}

    # Strip code fences if present.
    text = text.replace("```json", "").replace("```", "")

    # Find every top-level {...} candidate and take the first that parses with a
    # known action.
    candidates = re.findall(r"\{[^{}]*\}", text)
    for c in candidates:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("action") in _ACTIONS:
            return _coerce(obj)

    # Last resort: try to json-load the whole thing.
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict) and obj.get("action") in _ACTIONS:
            return _coerce(obj)
    except Exception:
        pass

    return {"action": "scroll", "dy": 200, "_repair": f"unparseable:{text[:80]!r}"}


def _coerce(obj: dict) -> dict:
    """Coerce field types and clamp coordinates into the viewport."""
    a = obj.get("action")
    out: dict = {"action": a}
    if a == "click":
        out["x"] = max(0, min(VIEWPORT_W - 1, int(obj.get("x", 0))))
        out["y"] = max(0, min(VIEWPORT_H - 1, int(obj.get("y", 0))))
    elif a == "type":
        out["text"] = str(obj.get("text", ""))
    elif a == "scroll":
        out["dy"] = int(obj.get("dy", 0))
    elif a == "navigate_back":
        pass
    elif a == "done":
        try:
            out["item_id"] = int(obj.get("item_id"))
        except (TypeError, ValueError):
            out["item_id"] = -1
    return out


@app.cls(
    image=inference_image,
    gpu=GPU,
    volumes={"/adapter_vol": ckpt_vol, "/cache": hf_cache_vol},
    secrets=[hf_secret],
    timeout=60 * 10,
    # GPU cost guardrails (account limit is 10 GPUs). HARD cap at 2 A100s so the
    # fleet's concurrent inference can never autoscale us to the limit, scale to
    # zero when idle (no paying for warm GPUs between demos), release fast.
    # Bump min_containers to 1 right before a live demo if you want it pre-warmed.
    min_containers=1,
    max_containers=2,
    scaledown_window=60,
)
class Policy:
    @modal.enter()
    def load(self):
        import torch

        os.environ.setdefault("HF_HOME", "/cache/hf")
        _resolve_hf_token()

        t0 = time.time()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.adapter_loaded = False

        adapter_path = "/adapter_vol/adapter"
        try:
            ckpt_vol.reload()
        except Exception:
            pass
        have_adapter = os.path.isdir(adapter_path) and os.path.exists(
            os.path.join(adapter_path, "adapter_config.json")
        )

        # --- Tier 1: load the adapter the way it was TRAINED (Unsloth) ----------
        # The committed LoRA was trained with Unsloth FastVisionModel against
        # `unsloth/gemma-4-e2b-it-unsloth-bnb-4bit`; its adapter_config targets
        # Unsloth-patched modules. Mirror that stack so the LoRA target modules
        # line up, then merge for plain `.generate()`. This is the path that
        # actually serves the FINE-TUNED policy (enables real purchases).
        self.model = None
        self.processor = None
        if have_adapter:
            try:
                from unsloth import FastVisionModel
                from peft import PeftModel

                base, processor = FastVisionModel.from_pretrained(
                    UNSLOTH_MODEL_ID,
                    load_in_4bit=True,
                    dtype=None,
                )
                model = PeftModel.from_pretrained(base, adapter_path)
                # Merge so inference is a single forward pass (no PEFT dispatch).
                try:
                    model = model.merge_and_unload()
                except Exception as merge_err:
                    # 4-bit merge can be unsupported; keep the un-merged PEFT model.
                    print(f"[serve] adapter merge skipped ({merge_err}); using PEFT-wrapped model")
                FastVisionModel.for_inference(model)
                self.model = model
                self.processor = processor
                self.adapter_loaded = True
                print(f"[serve] LoRA adapter loaded via Unsloth from {adapter_path}")
            except Exception as e:
                # Never crash-loop the container on an adapter load failure: log it
                # and fall through to serving the BASE model so the endpoint stays up.
                import traceback
                print(f"[serve] Unsloth adapter load FAILED: {type(e).__name__}: {e}")
                print(traceback.format_exc()[-1500:])
                self.model = None
                self.processor = None
                self.adapter_loaded = False

        # --- Tier 2: BASE model via plain transformers (no adapter / fallback) --
        if self.model is None:
            from transformers import AutoProcessor, AutoModelForImageTextToText

            self.processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
            self.model = AutoModelForImageTextToText.from_pretrained(
                MODEL_ID,
                torch_dtype=torch.bfloat16,
                device_map="cuda" if self.device == "cuda" else None,
                trust_remote_code=True,
            )
            if have_adapter:
                print("[serve] adapter present but unloadable -- serving BASE model (fallback)")
            else:
                print(f"[serve] no adapter at {adapter_path} -- serving BASE model")

        self.model.eval()
        self.gpu_name = torch.cuda.get_device_name(0) if self.device == "cuda" else "CPU"
        print(
            f"[serve] loaded on {self.gpu_name} "
            f"(adapter={self.adapter_loaded}) in {time.time() - t0:.1f}s"
        )

    def _infer(self, image, goal: str) -> dict:
        import torch

        user_text = build_user_text(goal)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": user_text},
                ],
            }
        ]
        inputs = self.processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.model.device)

        in_len = inputs["input_ids"].shape[-1]
        with torch.no_grad():
            gen = self.model.generate(
                **inputs,
                max_new_tokens=64,
                do_sample=False,          # greedy / temp 0
                num_beams=1,
            )
        new_tokens = gen[0][in_len:]
        raw = self.processor.decode(new_tokens, skip_special_tokens=True).strip()
        action = _extract_action_json(raw)
        return {"action": action, "raw": raw}

    @modal.method()
    def predict(self, image_b64: str, goal: str) -> dict:
        """RPC entrypoint (used by the fleet via modal.Cls lookup)."""
        import base64
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        out = self._infer(img, goal)
        out["adapter_loaded"] = self.adapter_loaded
        out["gpu"] = self.gpu_name
        return out

    @modal.fastapi_endpoint(method="POST", docs=True)
    def infer(self, payload: dict):
        """HTTP endpoint. Body: {"image_b64": "<base64 png>", "goal": "<text>"}.

        Returns: {"action": {...}, "raw": "...", "adapter_loaded": bool, "gpu": str}.
        """
        import base64
        import io
        from PIL import Image

        image_b64 = payload.get("image_b64")
        goal = payload.get("goal", "")
        if not image_b64:
            return {"error": "image_b64 required"}
        img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        out = self._infer(img, goal)
        out["adapter_loaded"] = self.adapter_loaded
        out["gpu"] = self.gpu_name
        return out


# ---------------------------------------------------------------------------
# In-container smoke: load the model and run inference on ONE real screenshot
# from the training set (uploaded inline). Confirms gemma4 vision loads on the
# GPU and returns a parseable action. Does NOT require the adapter.
# ---------------------------------------------------------------------------
@app.function(
    image=inference_image,
    gpu=GPU,
    volumes={"/adapter_vol": ckpt_vol, "/cache": hf_cache_vol},
    secrets=[hf_secret],
    timeout=60 * 15,
)
def smoke(image_b64: str, goal: str = "category=Phones, brand=OnePlus | site=site-a"):
    """Self-contained smoke: instantiate the Policy logic and infer once."""
    import base64
    import io
    import torch
    from PIL import Image
    from transformers import AutoProcessor, AutoModelForImageTextToText

    os.environ.setdefault("HF_HOME", "/cache/hf")
    _resolve_hf_token()

    report = {
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO GPU",
        "model_id": MODEL_ID,
        "adapter_loaded": False,
        "weights_loaded": False,
    }
    print(f"[smoke] GPU: {report['gpu']}")

    t0 = time.time()
    adapter_path = "/adapter_vol/adapter"
    try:
        ckpt_vol.reload()
    except Exception:
        pass
    have_adapter = os.path.isdir(adapter_path) and os.path.exists(
        os.path.join(adapter_path, "adapter_config.json")
    )

    # Mirror Policy.load: the LoRA was trained with Unsloth, so load it via Unsloth
    # (target modules line up); fall back to BASE if that fails or no adapter.
    model = None
    processor = None
    if have_adapter:
        try:
            from unsloth import FastVisionModel
            from peft import PeftModel

            base, processor = FastVisionModel.from_pretrained(
                UNSLOTH_MODEL_ID, load_in_4bit=True, dtype=None,
            )
            model = PeftModel.from_pretrained(base, adapter_path)
            try:
                model = model.merge_and_unload()
            except Exception as merge_err:
                print(f"[smoke] adapter merge skipped ({merge_err}); using PEFT-wrapped model")
            FastVisionModel.for_inference(model)
            report["adapter_loaded"] = True
            print(f"[smoke] adapter loaded via Unsloth from {adapter_path}")
        except Exception as e:
            print(f"[smoke] Unsloth adapter load FAILED: {type(e).__name__}: {e}")
            model = None
            processor = None

    if model is None:
        processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        model = AutoModelForImageTextToText.from_pretrained(
            MODEL_ID, torch_dtype=torch.bfloat16, device_map="cuda", trust_remote_code=True,
        )
        print("[smoke] adapter present but unloadable -> BASE model" if have_adapter
              else "[smoke] no adapter -> BASE model")
    report["weights_loaded"] = True
    report["load_s"] = round(time.time() - t0, 1)
    model.eval()

    img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
    report["image_size"] = list(img.size)

    user_text = build_user_text(goal)
    messages = [{
        "role": "user",
        "content": [{"type": "image", "image": img}, {"type": "text", "text": user_text}],
    }]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt",
    ).to(model.device)
    in_len = inputs["input_ids"].shape[-1]

    t1 = time.time()
    with torch.no_grad():
        gen = model.generate(**inputs, max_new_tokens=64, do_sample=False, num_beams=1)
    raw = processor.decode(gen[0][in_len:], skip_special_tokens=True).strip()
    report["infer_s"] = round(time.time() - t1, 1)
    report["raw_output"] = raw
    action = _extract_action_json(raw)
    report["action"] = action
    report["action_valid"] = action.get("action") in _ACTIONS and "_repair" not in action

    print("\n========== SERVE SMOKE REPORT ==========")
    print(f"gpu            : {report['gpu']}")
    print(f"weights_loaded : {report['weights_loaded']}")
    print(f"adapter_loaded : {report['adapter_loaded']}")
    print(f"load_s         : {report['load_s']}")
    print(f"infer_s        : {report['infer_s']}")
    print(f"raw_output     : {raw!r}")
    print(f"parsed action  : {action}")
    print(f"action_valid   : {report['action_valid']}")
    print("========================================\n")
    return report


@app.local_entrypoint()
def main(image_path: str = ""):
    """Smoke from the CLI with one real screenshot.

    Picks the first image under data/datasets/buyer/images/ if none given.
        modal run serve_modal.py
        modal run serve_modal.py --image-path /abs/path/to/shot.png
    """
    import base64
    import glob

    if not image_path:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cands = sorted(glob.glob(os.path.join(repo, "data", "datasets", "buyer", "images", "*_0.png")))
        if not cands:
            cands = sorted(glob.glob(os.path.join(repo, "data", "datasets", "buyer", "images", "*.png")))
        assert cands, "no screenshots found under data/datasets/buyer/images/"
        image_path = cands[0]
    print(f"[smoke] using screenshot: {image_path}")

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    report = smoke.remote(b64)
    print("RETURNED REPORT:", json.dumps(report, indent=2))
