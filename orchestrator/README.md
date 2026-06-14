# orchestrator — the live end-to-end glue

Turns **one typed goal** into a **live fleet** of buyer agents, streams them onto
the deployed Mission Control, and routes human-decision moments to the supervisor —
then resumes the agent on the human's verdict. This dir is the glue; the three
pieces it wires together (`runtime/`, `mission_control/`, the `sivra.io`
supervisor) are finished.

```
user types a goal
   │  POST /launch
   ▼
goal_parser   ── free text → {site, taskSpec} × N  (category / brand / €budget)
   ▼
fleet_driver  ── N buyer agents (runtime/agent_loop.run_episode) on the live
   │             marketplace via the Modal Gemma-4 policy
   │  every ~1s: POST {agents,stats} ──▶  Mission Control  POST /api/ingest
   │             (deployed dashboard shows the LIVE fleet — real screenshots)
   │
   └─ at a decision moment (forced demo step, or a natural buy / over-budget):
        POST sivra.io/escalate  ──▶ supervisor routes + pings a human (SMS/phone/web)
        tile flips to status=escalated ("awaiting human") on the dashboard
        poll sivra.io/resolution/{id} … human answers on /d/{code}
        approve → resume & complete · decline → move on · counter → adjust
```

## Files

| file | role |
|------|------|
| `app.py`         | FastAPI: `/` launcher page, `POST /launch`, `GET /status[/{id}]`, `/health` |
| `goal_parser.py` | free-text goal → satisfiable `{site, taskSpec}` tasks (category/brand/budget) |
| `fleet_driver.py`| in-process fleet runner (reuses `runtime/agent_loop`) + Mission Control PUSH loop + escalation capture |
| `ui.py`          | the launcher page (sivra design) — goal box, Launch button, live mission status + escalation reply links |
| `run.sh`         | start the server (sources repo-root `.env`) |
| `requirements.txt` | fastapi, uvicorn, httpx, python-dotenv, pydantic, playwright |
| `.venv/`         | self-contained venv (Python 3.12); reuses the chromium already in `~/Library/Caches/ms-playwright` |

## Launch a mission

The marketplace must be up at `http://localhost:3000` (the agents drive it).

```bash
cd orchestrator
./run.sh                      # serves http://localhost:8800  (PORT=8800 to override)
# open http://localhost:8800/ , type a goal, hit "Launch mission"
```

…or headless, via the API:

```bash
curl -s -X POST http://localhost:8800/launch \
  -H 'Content-Type: application/json' \
  -d '{"goal":"a used road bike, 56cm, under €400","n":12}'
```

Then watch the **deployed** dashboard go live:
**https://mission-control-production-332c.up.railway.app**
and the human queue at **https://sivra.io/pending**.

`GET http://localhost:8800/status` shows each mission's by-status counts, push
health, and per-escalation reply links.

## Config (env / repo-root `.env`, no secrets printed)

| var | default | purpose |
|-----|---------|---------|
| `SERVE_ENDPOINT` | the deployed Modal endpoint | buyer-vision policy |
| `MISSION_CONTROL_URL` | the Railway dashboard | we POST `{…}/api/ingest` |
| `SUPERVISOR_URL` | `https://sivra.io` | escalation target (read by `runtime/agent_loop`) |
| `MARKETPLACE_URL` | `http://localhost:3000` | where the agents shop |
| `MISSION_N` / `MISSION_MAX_N` | 12 / 100 | default / cap agents per mission |
| `INGEST_TOKEN` | _(unset)_ | optional shared secret for `/api/ingest` |
| `FORCE_ESCALATE_STEP` | `2` | demo lever: force one escalation at this step (set `-1` to rely only on natural buy/over-budget triggers) |
| `BUYER_BUDGET_EUR` | `400` | default budget cap; `taskSpec.maxPriceCents` overrides per-agent |
| `ESCALATION_TIMEOUT_S` | `180` | how long an agent waits for the human before moving on |

## Live vs stubbed (honest status with the base model)

- **Live now:** goal → fleet spawn; agents drive the real marketplace; real
  screenshots stream to the **deployed** dashboard (`source:"live"`); escalations
  reach `sivra.io/escalate`, appear at `/pending`, render at `/d/{code}`, and the
  human's answer flows back so the agent **resumes** (approve→continue,
  decline→move on). Verified: an agent escalated, a human approved on the web page,
  and the agent resumed (`escalated → running`); a separate decline moved its agent
  on (`escalated → done`).
- **Stubbed pending the adapter:** the *trigger* is forced at `FORCE_ESCALATE_STEP=2`
  with a placeholder over-budget price (`budget+€20`), because the **base** Gemma-4
  doesn't yet shop well enough to reach a real buy step. Once the trained LoRA lands
  and agents reach `done`/over-budget naturally, the same hook fires on its own —
  set `FORCE_ESCALATE_STEP=-1` to disable the demo lever.

## Swap to the trained adapter (one command)

Nothing in this dir changes. Bounce the Modal serving app so a fresh warm
container re-reads the checkpoint volume (it auto-loads `/adapter` if present):

```bash
cd ../runtime && set -a; source ../.env; set +a && .venv/bin/modal deploy serve_modal.py
```

Confirm it took: an `infer` response now returns `"adapter_loaded": true`.
```
