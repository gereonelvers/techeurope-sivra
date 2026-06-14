# sivra · console

A small internal web **console** to play with / test the live SMS and voice
escalation tiers. One FastAPI service serving a single HTML page; each tool POSTs
to a thin same-origin proxy here so the Telnyx key never reaches the browser and
we avoid CORS against `sivra.io`.

It only talks to the **public HTTP surfaces** of the already-deployed system — it
does not import or modify `supervisor/`, `voice/`, `agent/`, `pioneer/`, `apps/`.

## Tools (single page at `/`)

1. **Send an SMS delegation** — presets (over-budget laptop / pickup confirmation /
   safety flag) or a custom form → `POST {SUPERVISOR_URL}/escalate`. Shows the
   routing decision, the reply link `…/d/<first 6 of request_id>`, and whether an
   SMS was sent.
2. **Place a voice call** — runs the escalate→`/call` flow: first creates a
   voice-tier delegation (a safety-flag scenario the router tags `urgency_tier:
   voice`) to get a real `request_id`, then `POST {VOICE_URL}/call` with it so the
   bridge can resolve the delegation after the call. Editable `to` + context.
3. **Raw SMS** — arbitrary text to an arbitrary number straight through
   `POST https://api.telnyx.com/v2/messages` (sender `TELNYX_ALPHA_SENDER`). Smoke tool.
4. **Recent delegations** — renders `GET {SUPERVISOR_URL}/pending`.

## Files

```
console/
├── app.py            FastAPI app + /api/* server-side proxies (escalate/call/raw-sms/pending)
├── ui.py             the single HTML page (sivra design language) + vanilla-JS client
├── requirements.txt  fastapi, uvicorn, httpx, python-dotenv, pydantic
├── Dockerfile        python:3.12-slim, no audio stack
├── railway.json      Railway Dockerfile builder + start command
├── .dockerignore / .railwayignore
└── .venv/            local venv (NOT the repo-root .venv)
```

## Config (env vars)

Read from env (`.env` locally via python-dotenv; Railway service vars in prod):

- `SUPERVISOR_URL` (default `https://sivra.io`)
- `VOICE_URL` (default `https://voice-production-2b12.up.railway.app`)
- `TELNYX_API_KEY`, `TELNYX_ALPHA_SENDER` (sender, falls back to `TELNYX_FROM`),
  `TELNYX_MESSAGING_PROFILE_ID`
- `SIVRA_DEMO_PHONE` — default recipient for the SMS/voice tools

## Live deployment (project "believable-comfort")

- **Service:** `console` (new service, alongside `supervisor` and `voice`)
- **URL:** `https://console-production-96d0.up.railway.app`
- **Health:** `GET /health`

## Local dev

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8799
# open http://127.0.0.1:8799/  (reads ../.env for keys)
```

## Deploy / redeploy

```bash
export RAILWAY_TOKEN=$(grep '^RAILWAY_API_KEY=' ../.env | cut -d= -f2-)   # project token
railway up --service console --detach
# vars (idempotent): railway variables --service console --set "KEY=val" --skip-deploys
```

> Note: `RAILWAY_API_KEY` in `.env` is a **project-scoped** token. It authorizes
> project-scoped commands (`status`, `up`, `variables`, `domain`) but NOT
> account-scoped ones (`whoami`, `list`, `link`). The service already exists, so
> redeploys just need `railway up --service console`.
