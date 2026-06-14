"""Daily auto-retrain → eval → promote loop for the Pioneer delegation router.

This is the cron body. One `run(trigger)` call:

  ① reads the app's GET /api/internal/router/state for the champion model + the
     resolved-feedback count since the last train (the sample watermark);
  ② if sampleCount < minSamples AND trigger == "cron" → record a `skipped`
     ModelTrainingRun and exit (a manual trigger always proceeds);
  ③ builds the merged feedback+base SFT dataset (pioneer.feedback_dataset + base),
     uploads it, starts a LoRA fine-tune on Qwen3-4B, waits for it to deploy →
     challenger job-id;
  ④ evaluates champion vs challenger on the held-out router eval set (reuses
     eval/run_eval.py to score two Pioneer job-ids → person_acc, urgency_acc,
     delegate_acc, exact_match);
  ⑤ PROMOTE GATE — promote the challenger iff it WINS:
        exact_match(challenger) >= exact_match(champion)
        AND person_acc and urgency_acc each regress by no more than 0.02
     On promote → call the app POST /api/internal/router/promote (DB write, no
     redeploy). Otherwise record `kept`.
  ⑥ records the full ModelTrainingRun via the app (champion/challenger scores +
     decision). Never leaves a dangling `running` row — every exit path finalizes.

App access: prefer the internal HTTP API (APP_INTERNAL_URL + INTERNAL_API_TOKEN).
The state/runs/promote endpoints are the only writers of the product DB, per
ARCHITECTURE.md, so the cron never touches Postgres directly.

Runnable:
    python -m pioneer.auto_retrain                 # cron run (respects threshold)
    python -m pioneer.auto_retrain --trigger manual --dry-run-train  # eval-only smoke
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

# Load both env files; root .env holds the Pioneer/DB keys, apps/web/.env may add
# the internal token. Existing process env wins (Railway injects vars directly).
load_dotenv(str(ROOT / "apps" / "web" / ".env"), override=False)
load_dotenv(str(ROOT / ".env"), override=False)

log = logging.getLogger("auto_retrain")

# Promote gate constants.
REGRESSION_TOLERANCE = 0.02  # person_acc / urgency_acc may not drop more than this

PROMOTE_BASE_MODEL = os.getenv("PIONEER_BASE_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
EVAL_LIMIT = int(os.getenv("RETRAIN_EVAL_LIMIT", "60"))


# ── app internal API client (the only writer of the product DB) ───────────────
class AppClient:
    """Thin client over the app's /api/internal/router/* endpoints."""

    def __init__(self) -> None:
        base = os.getenv("APP_INTERNAL_URL") or os.getenv("SUPERVISOR_URL") or ""
        self.base = base.rstrip("/")
        self.token = os.getenv("INTERNAL_API_TOKEN", "")
        if not self.base:
            raise RuntimeError(
                "APP_INTERNAL_URL (or SUPERVISOR_URL) not set — the cron needs the "
                "app's base URL to read state / record runs / promote."
            )
        import httpx  # local import so import-time never needs httpx

        self._httpx = httpx

    def _h(self) -> dict:
        return {"x-internal-token": self.token, "Content-Type": "application/json"}

    def get_state(self) -> dict:
        r = self._httpx.get(f"{self.base}/api/internal/router/state",
                            headers=self._h(), timeout=30)
        r.raise_for_status()
        return r.json()

    def record_run(self, **fields) -> str:
        r = self._httpx.post(f"{self.base}/api/internal/router/runs",
                            headers=self._h(), json=fields, timeout=30)
        r.raise_for_status()
        return r.json().get("run", {}).get("id", "")

    def promote(self, model_id: str, sample_count: int) -> dict:
        r = self._httpx.post(f"{self.base}/api/internal/router/promote",
                            headers=self._h(),
                            json={"modelId": model_id, "sampleCount": sample_count},
                            timeout=30)
        r.raise_for_status()
        return r.json()


# ── eval: score two Pioneer job-ids on the held-out router eval set ───────────
def _load_run_eval():
    """Import eval/run_eval.py (not a package) by path, to reuse its harness."""
    spec = importlib.util.spec_from_file_location("run_eval", str(ROOT / "eval" / "run_eval.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def eval_two_models(champion: str, challenger: str, limit: int = EVAL_LIMIT) -> tuple[Optional[dict], Optional[dict]]:
    """Score champion + challenger Pioneer job-ids on the held-out eval set.

    Returns ({champion scores}, {challenger scores}); either may be None if that
    model's eval failed (e.g. an inference error). Scores carry person_acc,
    urgency_acc, delegate_acc, exact_match, p50_ms, cost_per_1k_usd."""
    re = _load_run_eval()
    rows = re.load_eval(limit)
    log.info("eval set: %d held-out examples", len(rows))
    champ = re.evaluate(f"pioneer:{champion}", rows)
    chall = re.evaluate(f"pioneer:{challenger}", rows)
    return champ, chall


def promote_gate(champ: Optional[dict], chall: Optional[dict]) -> tuple[bool, str]:
    """The promote decision. Promote the challenger iff it WINS:
        exact_match(chall) >= exact_match(champ)
        AND person_acc and urgency_acc each regress <= REGRESSION_TOLERANCE.
    Returns (promote: bool, reason: str)."""
    if chall is None:
        return False, "challenger eval failed (no scores)"
    if champ is None:
        # No champion scores to compare against → adopt the challenger (it at least ran).
        return True, "champion eval failed; adopting challenger that scored"

    em_ok = chall["exact_match"] >= champ["exact_match"]
    person_reg = champ["person_acc"] - chall["person_acc"]
    urgency_reg = champ["urgency_acc"] - chall["urgency_acc"]
    person_ok = person_reg <= REGRESSION_TOLERANCE
    urgency_ok = urgency_reg <= REGRESSION_TOLERANCE

    promote = em_ok and person_ok and urgency_ok
    reason = (
        f"exact_match {chall['exact_match']:.3f} {'>=' if em_ok else '<'} "
        f"{champ['exact_match']:.3f}; person regress {person_reg:+.3f} "
        f"({'ok' if person_ok else 'FAIL'}); urgency regress {urgency_reg:+.3f} "
        f"({'ok' if urgency_ok else 'FAIL'}) — tol {REGRESSION_TOLERANCE}"
    )
    return promote, reason


# ── training: build merged dataset → upload → train → wait → challenger id ─────
def train_challenger(min_reward: float = 0.0, use_postgres: bool = True,
                     base_model: str = PROMOTE_BASE_MODEL, epochs: int = 1,
                     pipeclean: bool = False, limit: int = 256) -> tuple[str, str]:
    """Build the merged feedback+base dataset, upload it, start + wait a LoRA
    fine-tune. Returns (challenger_job_id, dataset_id_or_name)."""
    from pioneer import retrain as retrain_mod
    from pioneer.client import PioneerClient

    plan = retrain_mod.build_merged(min_reward=min_reward, use_postgres=use_postgres)
    log.info("merged dataset: %d rows (base=%d, feedback=%d)",
             plan["merged_rows"], plan["base_rows"], plan["feedback_rows"])

    if pipeclean:
        lines = [l for l in retrain_mod.MERGED_SFT.read_text().splitlines() if l.strip()]
        fb_n = plan["feedback_rows"]
        head = max(0, limit - fb_n)
        subset = (lines[:head] + lines[-fb_n:]) if fb_n else lines[:limit]
        retrain_mod.PIPECLEAN_SFT.write_text("\n".join(subset[:limit]) + "\n")
        train_path = retrain_mod.PIPECLEAN_SFT
        dataset_name = f"router-sft-auto-pipeclean-{int(time.time())}"
        model_name = "delegation-router-auto-pipeclean"
    else:
        train_path = retrain_mod.MERGED_SFT
        dataset_name = f"router-sft-auto-{int(time.time())}"
        model_name = "delegation-router-auto"

    c = PioneerClient()
    log.info("uploading %s as '%s' ...", train_path.name, dataset_name)
    ds_id = c.upload_dataset(dataset_name, str(train_path), dataset_type="decoder",
                             split="training")
    c.wait_dataset(ds_id, name=dataset_name)
    log.info("dataset ready id=%s; starting fine-tune (base=%s, epochs=%d) ...",
             ds_id, base_model, epochs)
    job = c.create_training_job(model_name, base_model, dataset_name, nr_epochs=epochs)
    job_id = job.get("id") or job.get("data", {}).get("id")
    if not job_id:
        raise RuntimeError(f"no job id from create_training_job: {job}")
    log.info("training job %s started; waiting for deploy ...", job_id)
    c.wait_job(job_id)
    log.info("training job %s deployed", job_id)
    return job_id, ds_id


# ── the cron body ─────────────────────────────────────────────────────────────
def run(trigger: str = "cron", *, dry_run_train: bool = False,
        challenger_override: Optional[str] = None, pipeclean: bool = True,
        eval_limit: int = EVAL_LIMIT) -> dict:
    """Run one retrain→eval→promote cycle. `trigger` ∈ {cron, manual}.

    dry_run_train      : skip training; eval an existing challenger (for smoke tests).
    challenger_override : use THIS job-id as the challenger (with dry_run_train).
    pipeclean          : when training, do the tiny 1-epoch validation train.

    Returns a summary dict. Always finalizes the ModelTrainingRun (never dangling).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=False,
    )
    log.info("=== auto_retrain.run(trigger=%s) ===", trigger)

    app = AppClient()

    # ① read state
    state = app.get_state()
    champion = state["activeModelId"]
    sample_count = int(state.get("sampleCount", 0))
    min_samples = int(state.get("minSamples", 50))
    auto_enabled = bool(state.get("autoRetrainEnabled", True))
    log.info("champion=%s sampleCount=%d minSamples=%d autoRetrainEnabled=%s",
             champion, sample_count, min_samples, auto_enabled)

    # ② threshold / enabled gate (cron only; manual always proceeds)
    if trigger == "cron" and not auto_enabled:
        run_id = app.record_run(status="succeeded", triggeredBy=trigger,
                                sampleCount=sample_count, championModelId=champion,
                                decision="skipped", notes="auto-retrain disabled",
                                finishedAt=_now_iso())
        log.info("auto-retrain disabled → skipped (run %s)", run_id)
        return {"decision": "skipped", "reason": "disabled", "run_id": run_id}

    if trigger == "cron" and sample_count < min_samples:
        run_id = app.record_run(status="succeeded", triggeredBy=trigger,
                                sampleCount=sample_count, championModelId=champion,
                                decision="skipped",
                                notes=f"{sample_count} < {min_samples} samples",
                                finishedAt=_now_iso())
        log.info("below threshold (%d < %d) → skipped (run %s)",
                 sample_count, min_samples, run_id)
        return {"decision": "skipped", "reason": "below_threshold", "run_id": run_id}

    # open the run row up front so a crash is visible as a finalized failure.
    run_id = app.record_run(status="running", triggeredBy=trigger,
                            sampleCount=sample_count, championModelId=champion,
                            notes="started")
    log.info("opened ModelTrainingRun %s", run_id)

    try:
        # ③ train challenger (or use an override for smoke tests)
        dataset_id: Optional[str] = None
        if dry_run_train:
            challenger = challenger_override
            if not challenger:
                raise RuntimeError("dry_run_train requires --challenger <job-id>")
            log.info("dry_run_train: skipping training; challenger=%s", challenger)
        else:
            challenger, dataset_id = train_challenger(
                base_model=PROMOTE_BASE_MODEL, epochs=1, pipeclean=pipeclean)

        app.record_run(id=run_id, challengerModelId=challenger, datasetId=dataset_id,
                       notes="trained; evaluating")

        # ④ eval champion vs challenger
        champ_scores, chall_scores = eval_two_models(champion, challenger, limit=eval_limit)
        log.info("champion  scores: %s", _fmt_scores(champ_scores))
        log.info("challenger scores: %s", _fmt_scores(chall_scores))

        # ⑤ promote gate
        promote, reason = promote_gate(champ_scores, chall_scores)
        log.info("promote gate: %s — %s", promote, reason)

        decision = "promoted" if promote else "kept"
        if promote:
            res = app.promote(challenger, sample_count)
            log.info("PROMOTED challenger %s → activeModelId=%s version=%s",
                     challenger, res.get("activeModelId"), res.get("version"))
        else:
            log.info("KEPT champion %s (challenger did not win)", champion)

        # ⑥ finalize the run with the full record
        app.record_run(
            id=run_id, status="succeeded", decision=decision,
            championModelId=champion, challengerModelId=challenger,
            championScores=champ_scores, challengerScores=chall_scores,
            datasetId=dataset_id, sampleCount=sample_count,
            notes=reason, finishedAt=_now_iso(),
        )
        return {
            "decision": decision, "reason": reason, "run_id": run_id,
            "champion": champion, "challenger": challenger,
            "champion_scores": champ_scores, "challenger_scores": chall_scores,
        }

    except Exception as e:  # never leave a dangling `running` row
        log.exception("auto_retrain failed: %s", e)
        try:
            app.record_run(id=run_id, status="failed", decision="failed",
                           notes=f"{type(e).__name__}: {str(e)[:300]}",
                           finishedAt=_now_iso())
        except Exception:
            log.exception("ALSO failed to finalize the run row")
        return {"decision": "failed", "reason": str(e), "run_id": run_id}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _fmt_scores(s: Optional[dict]) -> str:
    if not s:
        return "FAILED"
    return (f"person={s['person_acc']:.3f} urgency={s['urgency_acc']:.3f} "
            f"delegate={s['delegate_acc']:.3f} exact={s['exact_match']:.3f} "
            f"p50={s['p50_ms']:.0f}ms")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trigger", choices=["cron", "manual"], default="cron")
    ap.add_argument("--dry-run-train", action="store_true",
                    help="skip training; eval an existing --challenger job-id")
    ap.add_argument("--challenger", default=None, help="job-id to eval (with --dry-run-train)")
    ap.add_argument("--no-pipeclean", action="store_true",
                    help="do a FULL train instead of the tiny pipeclean run")
    ap.add_argument("--eval-limit", type=int, default=EVAL_LIMIT)
    args = ap.parse_args()

    summary = run(
        trigger=args.trigger,
        dry_run_train=args.dry_run_train,
        challenger_override=args.challenger,
        pipeclean=not args.no_pipeclean,
        eval_limit=args.eval_limit,
    )
    print("\n=== auto_retrain summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0 if summary.get("decision") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
