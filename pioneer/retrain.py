"""Loop A, step 2 — retrain the delegation router from human feedback.

Closes the Pioneer self-improvement loop end-to-end:

  (a) regenerate the feedback dataset from resolved human corrections
      (pioneer/feedback_dataset.py — Postgres Escalations + legacy reward log),
  (b) merge it with the base synthetic SFT (data/datasets/router_sft.jsonl) into
      data/datasets/router_sft_merged.jsonl (feedback rows appended LAST so they
      are the most recent gradient signal),
  (c) hand the merged dataset to the existing upload+train path in pioneer/train.py
      (PioneerClient.upload_dataset -> create_training_job).

DRY-RUN BY DEFAULT. Without --submit this builds + validates the dataset, prints
EXACTLY what a real run would upload/train, and stops. The actual remote submit is
guarded behind --submit because Pioneer dataset-write + training currently 403 with
`card_verification_required` until the account has a plan/card (see pioneer/client.py).

    python pioneer/retrain.py                 # dry-run: build + validate + print plan
    python pioneer/retrain.py --pipeclean     # dry-run plan for the tiny validation run
    python pioneer/retrain.py --submit         # ACTUALLY upload+train (will 403 today)
    python pioneer/retrain.py --submit --pipeclean --wait
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(ROOT / ".env"), override=True)

from pioneer import feedback_dataset  # noqa: E402

DATASETS = ROOT / "data" / "datasets"
BASE_SFT = DATASETS / "router_sft.jsonl"
FEEDBACK_SFT = DATASETS / "router_sft_feedback.jsonl"
MERGED_SFT = DATASETS / "router_sft_merged.jsonl"
PIPECLEAN_SFT = DATASETS / "router_sft_retrain_pipeclean.jsonl"


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.strip())


def _validate_sft(p: Path) -> tuple[int, int]:
    """Return (valid, invalid) — a line is valid if it has the 3-role chat shape
    and the assistant turn parses as JSON with the router target keys."""
    valid = invalid = 0
    keys = {"should_delegate", "target_person", "urgency_tier", "suggested_message"}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msgs = json.loads(line)["messages"]
            assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
            tgt = json.loads(msgs[2]["content"])
            assert keys.issubset(tgt.keys())
            valid += 1
        except Exception:
            invalid += 1
    return valid, invalid


def build_merged(min_reward: float, use_postgres: bool) -> dict:
    """Regenerate feedback dataset, merge with base, write merged file. Returns a
    plan dict describing the result (no network training)."""
    if not BASE_SFT.exists():
        raise SystemExit(
            f"missing base synthetic SFT {BASE_SFT} — run: python pioneer/dataset.py"
        )

    # (a) regenerate feedback dataset
    fb_records, fb_summary = feedback_dataset.build(
        out=FEEDBACK_SFT, min_reward=min_reward, use_postgres=use_postgres,
        write_file=True,
    )

    # (b) merge: base first, feedback appended last (freshest signal last)
    base_lines = [l for l in BASE_SFT.read_text().splitlines() if l.strip()]
    fb_lines = [json.dumps(r, ensure_ascii=False) for r in fb_records]
    MERGED_SFT.write_text("\n".join(base_lines + fb_lines) + "\n")

    valid, invalid = _validate_sft(MERGED_SFT)
    return {
        "feedback_summary": fb_summary,
        "base_rows": len(base_lines),
        "feedback_rows": len(fb_lines),
        "merged_rows": valid + invalid,
        "merged_valid": valid,
        "merged_invalid": invalid,
        "merged_path": str(MERGED_SFT),
        "feedback_path": str(FEEDBACK_SFT),
    }


def _print_plan(plan: dict, base_model: str, epochs: int, dataset_name: str,
                model_name: str, train_path: Path, submit: bool) -> None:
    fb = plan["feedback_summary"]
    print("=" * 68)
    print("Loop A — Pioneer delegation-router retrain (feedback -> SFT -> train)")
    print("=" * 68)
    print(f"feedback examples   : {fb['total']}  "
          f"(reward_log={fb['reward_log']}, postgres={fb['postgres']} [{fb['postgres_status']}])")
    print(f"base synthetic rows : {plan['base_rows']}  ({BASE_SFT.name})")
    print(f"merged dataset      : {plan['merged_rows']} rows  "
          f"(valid={plan['merged_valid']}, invalid={plan['merged_invalid']})")
    print(f"  -> {plan['merged_path']}")
    print(f"  -> feedback file: {plan['feedback_path']}")
    print()
    print("WOULD SUBMIT to Pioneer (pioneer/train.py upload+train path):")
    print(f"  upload_dataset      name='{dataset_name}'  file={train_path.name} "
          f"({_count_lines(train_path)} rows)  type=decoder split=training")
    print(f"  create_training_job model_name='{model_name}'  base_model='{base_model}'  "
          f"epochs={epochs}  training_type=lora")
    print()
    if not submit:
        print("DRY-RUN (default): nothing was uploaded or trained.")
        print("  Re-run with --submit to actually upload + start the fine-tune.")
        print("  NOTE: Pioneer dataset-write + training currently 403 with")
        print("        `card_verification_required` until the account adds a plan/card")
        print("        (https://agent.pioneer.ai/billing). --submit will surface that 403.")
    print("=" * 68)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true",
                    help="ACTUALLY upload the dataset + start training (else dry-run)")
    ap.add_argument("--pipeclean", action="store_true",
                    help="use a tiny merged subset (cheap validation run)")
    ap.add_argument("--limit", type=int, default=64,
                    help="rows for the pipeclean subset")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--min-reward", type=float, default=feedback_dataset.DEFAULT_MIN_REWARD)
    ap.add_argument("--no-postgres", action="store_true",
                    help="skip the Postgres feedback source (use only the legacy log)")
    ap.add_argument("--base-model",
                    default=os.getenv("PIONEER_BASE_MODEL", "Qwen/Qwen3-4B-Instruct-2507"))
    ap.add_argument("--wait", action="store_true", help="poll the job to completion (with --submit)")
    args = ap.parse_args()

    plan = build_merged(min_reward=args.min_reward, use_postgres=not args.no_postgres)

    if args.pipeclean:
        # feedback rows are at the TAIL of the merged file; bias the pipeclean subset
        # to include them so a cheap validation run actually exercises the new data.
        lines = [l for l in MERGED_SFT.read_text().splitlines() if l.strip()]
        fb_n = plan["feedback_rows"]
        head = max(0, args.limit - fb_n)
        subset = lines[:head] + lines[-fb_n:] if fb_n else lines[:args.limit]
        PIPECLEAN_SFT.write_text("\n".join(subset[:args.limit]) + "\n")
        train_path = PIPECLEAN_SFT
        dataset_name, model_name, epochs = (
            "router-sft-feedback-pipeclean", "delegation-router-feedback-pipeclean", 1)
    else:
        train_path = MERGED_SFT
        dataset_name, model_name, epochs = (
            "router-sft-feedback-v1", "delegation-router-feedback-sft", args.epochs)

    _print_plan(plan, args.base_model, epochs, dataset_name, model_name, train_path, args.submit)

    if not args.submit:
        return 0

    # ── real submit path (guarded) ──────────────────────────────────────────
    from pioneer.client import PioneerClient, PioneerError
    c = PioneerClient()
    print(f"\n[submit] uploading {train_path.name} as '{dataset_name}' ...")
    try:
        ds_id = c.upload_dataset(dataset_name, str(train_path), dataset_type="decoder",
                                 split="training")
        print(f"[submit] uploaded dataset id={ds_id}; waiting until ready ...")
        c.wait_dataset(ds_id, name=dataset_name)
        job = c.create_training_job(model_name, args.base_model, dataset_name, nr_epochs=epochs)
        job_id = job.get("id") or job.get("data", {}).get("id")
        print(f"[submit] training job started: {job_id}")
        if args.wait and job_id:
            c.wait_job(job_id)
            print(f"\nDONE. set PIONEER_ROUTER_MODEL={job_id} and run the eval:")
            print(f'   python eval/run_eval.py --models "pioneer:{job_id},gemini:gemini-3.5-flash"')
    except PioneerError as e:
        msg = str(e)
        if "card_verification_required" in msg:
            print("\nPioneer needs a plan/card before it will accept writes (HTTP 403).")
            print("  Subscribe at https://agent.pioneer.ai/billing (or ask organizers for credits).")
            print("  The dataset is built + validated locally; --submit will work once billing is on.")
        else:
            print(f"\nPioneer error: {msg}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
