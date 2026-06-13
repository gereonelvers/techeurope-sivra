"""Fine-tune the delegation router on Pioneer.

    python pioneer/train.py --pipeclean       # tiny cheap validation run first
    python pioneer/train.py --wait            # full run, poll to completion

Once a run completes, set PIONEER_ROUTER_MODEL=<job_id> and compare it to the
frontier models:  python eval/run_eval.py --models "pioneer:<job_id>,gemini:gemini-3.5-flash"

NOTE: dataset upload + training currently 403 with `card_verification_required`
until the Pioneer account has a plan/card. The pipeclean run is the right way to
confirm the exact base_model id + dataset format before committing to a paid run.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(override=True)

from pioneer.client import PioneerClient, PioneerError  # noqa: E402

DATASETS = Path(__file__).resolve().parent.parent / "data" / "datasets"
SFT = DATASETS / "router_sft.jsonl"


def make_subset(n: int) -> Path:
    out = DATASETS / "router_sft_pipeclean.jsonl"
    lines = SFT.read_text().splitlines()[:n]
    out.write_text("\n".join(lines) + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeclean", action="store_true", help="tiny cheap validation run")
    ap.add_argument("--limit", type=int, default=24, help="examples for the pipeclean run")
    ap.add_argument("--epochs", type=int, default=3)
    # router is a TEXT task; use a clean text decoder (Gemma 4 vision goes on Modal, not here)
    ap.add_argument("--base-model", default=os.getenv("PIONEER_BASE_MODEL", "Qwen/Qwen3-4B-Instruct-2507"))
    ap.add_argument("--wait", action="store_true", help="poll the job to completion")
    args = ap.parse_args()

    if not SFT.exists():
        print(f"missing {SFT} — run: python pioneer/dataset.py")
        return 1

    c = PioneerClient()
    if args.pipeclean:
        path, name, model_name, epochs = make_subset(args.limit), "router-sft-pipeclean", "delegation-router-pipeclean", 1
    else:
        path, name, model_name, epochs = SFT, "router-sft-v1", "delegation-router-sft", args.epochs

    print(f"dataset: {path.name} ({len(path.read_text().splitlines())} rows) -> '{name}'")
    print(f"base_model: {args.base_model}  epochs: {epochs}")
    try:
        ds_id = c.upload_dataset(name, str(path), dataset_type="decoder", split="training")
        print(f"uploaded dataset id={ds_id}; waiting for it to be ready ...")
        c.wait_dataset(ds_id, name=name)
        job = c.create_training_job(model_name, args.base_model, name, nr_epochs=epochs)
        job_id = job.get("id") or job.get("data", {}).get("id")
        print(f"training job started: {job_id}")
        if args.wait and job_id:
            c.wait_job(job_id)
            print(f"\n✅ done. set PIONEER_ROUTER_MODEL={job_id} and run the eval:")
            print(f'   python eval/run_eval.py --models "pioneer:{job_id},gemini:gemini-3.5-flash"')
    except PioneerError as e:
        msg = str(e)
        if "card_verification_required" in msg:
            print("\n⚠️  Pioneer needs a plan/card before it will accept writes.")
            print("   Subscribe at https://agent.pioneer.ai/billing (or ask the organizers for credits).")
        else:
            print(f"\nPioneer error: {msg}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
