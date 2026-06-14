"""Cron entry for the daily delegation-router auto-retrain → eval → promote loop.

Railway runs this as a SCHEDULED service (cron). It does one pass and exits:
calls pioneer.auto_retrain.run("cron"), which respects the minSamples threshold,
trains a challenger, evals it against the champion, and promotes on a win (a DB
write via the app's internal API — no redeploy).

Exit code 0 on any clean decision (promoted/kept/skipped); non-zero only on a hard
failure, so Railway's run history flags genuine breakage.

Env it needs (see retrain_cron/README.md):
  APP_INTERNAL_URL    base URL of apps/web (state/runs/promote endpoints)
  INTERNAL_API_TOKEN  shared internal token (must match the app's)
  PIONEER_API_KEY     Pioneer API key (upload + train + inference)
  DATABASE_URL        Postgres (read resolved Escalations for the feedback dataset)
  PIONEER_BASE_URL    optional, defaults to https://api.pioneer.ai/v1
  PIONEER_BASE_MODEL  optional, defaults to Qwen/Qwen3-4B-Instruct-2507
  RETRAIN_EVAL_LIMIT  optional, held-out eval examples (default 60)
"""
import os
import sys

# Allow `python retrain_cron/run.py` from the repo root or the image WORKDIR.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pioneer.auto_retrain import run  # noqa: E402


def main() -> int:
    trigger = os.getenv("RETRAIN_TRIGGER", "cron")
    summary = run(trigger=trigger)
    print("\n=== retrain_cron summary ===", flush=True)
    for k, v in summary.items():
        print(f"  {k}: {v}", flush=True)
    # Only a hard failure is a non-zero exit; skipped/kept/promoted are all "fine".
    return 1 if summary.get("decision") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
