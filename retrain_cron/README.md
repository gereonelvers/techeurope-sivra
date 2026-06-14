# retrain_cron — daily delegation-router auto-retrain loop

A Railway **cron service** (no GPU) that runs the Pioneer delegation router's
`retrain → eval → promote` loop once a day. Pioneer does the fine-tune remotely;
this host only builds the dataset, drives the Pioneer API, evals champion vs
challenger on the held-out set, and **promotes by a DB write via the app** (no
redeploy).

Entry point: [`run.py`](./run.py) → `pioneer.auto_retrain.run("cron")`.

## What one run does
1. `GET {APP_INTERNAL_URL}/api/internal/router/state` → champion model + resolved
   feedback count since the last train + `minSamples`.
2. If `sampleCount < minSamples` (cron trigger) or auto-retrain is disabled →
   record a `skipped` ModelTrainingRun and exit 0.
3. Build merged feedback+base SFT (`pioneer.feedback_dataset` + base
   `data/datasets/router_sft.jsonl`), upload, start a **LoRA** fine-tune on
   `Qwen/Qwen3-4B-Instruct-2507`, wait for deploy → challenger job-id.
4. Eval champion vs challenger on `data/datasets/router_eval.jsonl` (person_acc,
   urgency_acc, delegate_acc, exact_match).
5. **Promote gate** — promote iff `exact_match(chall) >= exact_match(champ)` AND
   neither `person_acc` nor `urgency_acc` regresses by more than `0.02`. On
   promote → `POST /api/internal/router/promote`. Else record `kept`.
6. Record the full `ModelTrainingRun` (scores + decision). Never leaves a
   dangling `running` row — every exit path finalizes it.

## Env vars
| Var | Required | Purpose |
|---|---|---|
| `APP_INTERNAL_URL` | yes | Base URL of `apps/web` (e.g. `https://sivra.io`). The cron reads state / records runs / promotes through its `/api/internal/router/*` endpoints. (`SUPERVISOR_URL` is accepted as a fallback alias.) |
| `INTERNAL_API_TOKEN` | yes | Shared `x-internal-token` — must match the app's. |
| `PIONEER_API_KEY` | yes | Pioneer API key (dataset upload + train + inference). |
| `DATABASE_URL` | yes | Postgres (public Railway proxy URL) — `feedback_dataset.py` reads RESOLVED `Escalation` rows directly to build new SFT examples. Set to `${{Postgres.DATABASE_URL}}`. |
| `PIONEER_BASE_URL` | no | Defaults to `https://api.pioneer.ai/v1`. |
| `PIONEER_BASE_MODEL` | no | Defaults to `Qwen/Qwen3-4B-Instruct-2507`. |
| `RETRAIN_EVAL_LIMIT` | no | Held-out eval examples per model (default `60`). |
| `RETRAIN_TRIGGER` | no | `cron` (default) or `manual` (manual ignores the threshold). |

> The app side also reads an optional `RETRAIN_TRIGGER_URL` (the admin "Retrain
> now" button forwards there). If you expose a manual trigger, point that env at
> it; otherwise the button just tells the admin to run the cron manually.

## Railway cron setup (do NOT deploy yet — these are the exact steps)
1. **New service** in the existing Railway project → *Deploy from Repo* → pick this
   repo.
2. **Settings → Build**: Builder = *Dockerfile*, Dockerfile Path =
   `retrain_cron/Dockerfile`. **Leave the Root Directory at the repo root** — the
   Dockerfile `COPY`s `shared/`, `supervisor/`, `pioneer/`, `eval/`,
   `data/datasets/`, `config/`, so the build context must be the repo root.
3. **Settings → Deploy → Cron Schedule**: `0 3 * * *` (daily 03:00 UTC). Railway
   then runs the container on that schedule and expects it to **exit** (it's a job,
   not a long-running server). Our `run.py` does exactly one pass and exits.
4. **Settings → Deploy → Restart Policy**: `Never` (a cron job should not restart
   on its own exit; a non-zero exit is surfaced in the run history).
5. **Variables**: add the env vars above. Reference the Postgres plugin with
   `DATABASE_URL = ${{Postgres.DATABASE_URL}}`. `APP_INTERNAL_URL` =
   the `web` service URL (or `https://sivra.io`). `INTERNAL_API_TOKEN` must equal
   the `web` service's token.
6. Deploy. To test immediately without waiting for 03:00, open the service →
   **Deployments → Run now** (or temporarily set the schedule a couple of minutes
   ahead), then watch the logs for the `=== retrain_cron summary ===` block.

`railway.json` in this folder pre-fills builder + Dockerfile path + the
`0 3 * * *` schedule + `restartPolicyType: NEVER`, so most of the above is applied
automatically when the service uses this config.

## Run locally (smoke)
```bash
# eval-only smoke against an existing challenger (no training), from the repo root:
.venv/bin/python -m pioneer.auto_retrain --trigger manual --dry-run-train \
  --challenger 3649d82d-357b-44f1-b1d6-f83e80b2f9de --eval-limit 40

# full cron pass (respects the minSamples threshold):
.venv/bin/python retrain_cron/run.py
```
Requires `APP_INTERNAL_URL` + `INTERNAL_API_TOKEN` + `PIONEER_API_KEY` +
`DATABASE_URL` in the environment (or the repo `.env` / `apps/web/.env`).
