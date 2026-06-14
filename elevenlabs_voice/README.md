# sivra · Quartermaster Voice — ElevenLabs Conversational AI edition

The voice tier, rebuilt on **ElevenLabs Conversational AI**, replacing the flaky
Gemini-Live ⇄ Telnyx media bridge. When an escalation is urgent+complex
(`urgency_tier == "voice"`), the supervisor hits `POST {VOICE_URL}/call`; this
service starts an **ElevenLabs ConvAI outbound call** (ElevenLabs → Telnyx SIP
trunk → PSTN) that phones the human, explains the pending purchase, captures
their decision + feedback, and POSTs a `HumanResolution` straight back to the
supervisor. ElevenLabs runs the entire call server-side — no Pipecat, no media
websocket, no codec wrangling.

## Same contract as the old service

`POST /call` takes the identical `{request_id, to, context, person}` body and the
supervisor's existing call site works by just repointing `VOICE_URL`. `GET /health`
reports config sanity.

## Pieces

```
elevenlabs_voice/
├── app.py                  FastAPI service: POST /call -> ElevenLabs outbound-call API; GET /health
├── provision.py            idempotent: create/update the OUTBOUND escalation agent + submit_decision tool;
│                           --telephony sets up the outbound SIP trunk phone number
├── simulate.py             proves the OUTBOUND loop with ZERO phone calls (escalate -> simulate -> resolve)
├── provision_inbound.py    idempotent: create/update the INBOUND ordering agent + create_order tool;
│                           --routing wires inbound PSTN -> ElevenLabs (EL number + Telnyx repoint)
├── simulate_inbound.py     proves the INBOUND ordering agent + create_order with ZERO phone calls
├── Dockerfile              python:3.12-slim, thin (no audio stack)
├── railway.json            Railway Dockerfile builder + start command
└── requirements.txt
```

## The ConvAI agent

- **agent_id:** `agent_8501kv0thytseyvs2tsb7sbyzaz7` (name: "sivra Quartermaster Voice")
- LLM `gemini-2.5-flash`, voice **Charlotte** (`XB0fDUnXU5powFXDhCwa`), `eleven_turbo_v2` TTS.
- **Dynamic variables** per call: `{{request_id}}`, `{{context}}`, `{{person}}`.
- **First message** greets `{{person}}` and states `{{context}}`.
- **Server (webhook) tool `submit_decision`** → `POST https://sivra.io/resolve/{{rid}}`
  with a `HumanResolution` body: `request_id, resolution (approve|counter|decline),
  value?, notes?, resolved_by={{person}}, rating (good|wrong), corrected_person?,
  corrected_urgency?`. (`request_id` rides the URL path as `rid` AND the body — they
  must differ in name because ElevenLabs forbids duplicate param names across
  path/body, and the supervisor needs it in both.)

Re-run provisioning any time (idempotent — set `EL_AGENT_ID` to update in place):

```bash
.venv/bin/python provision.py              # create/update the agent, verify the tool
.venv/bin/python provision.py --telephony  # + set up the outbound SIP trunk phone number
```

## Telephony (outbound SIP trunk)

ElevenLabs ↔ Telnyx is wired for **outbound** PSTN:

- Telnyx FQDN SIP connection **VoxGuard-intern** (`2900679085086738176`, FQDN
  `sip.rtc.elevenlabs.io`, user `voxguard`) — the `VoxGuard` outbound voice profile
  (`2900274038037284437`, whitelists DE + US) is attached so Telnyx routes the call
  out to the PSTN.
- ElevenLabs outbound SIP-trunk phone number **`+14472154920`** (`TELNYX_FROM`),
  imported pointing at `sip.telnyx.com` with the connection's digest credentials,
  assigned to the agent.
  - **phone_number_id:** `phnum_5201kv0twb9cf3p901q4jds5t8tq` (`supports_outbound: true`)
- The pre-existing ElevenLabs number `+14408209523` ("VoxGuard Alex") is **inbound-only**,
  so it was not reused for outbound.

**Free-tier check:** the ElevenLabs account is on the **free tier**. Phone-number
import, SIP-trunk setup, and the outbound-call API are all **available on free tier**
— verified by importing the number (HTTP 200) and hitting the outbound-call API,
which created a conversation and sent a real SIP INVITE through Telnyx (it only
404'd because the *probe destination* was an unroutable test number — no plan
blocker). Free tier limits are on character/credit volume, not feature access.

## Inbound voice ordering (NEW — an employee CALLS to place an order)

The second voice path: an employee **calls** `+14472154920` and places a purchase
order by voice. A **separate** ConvAI agent handles this — the outbound escalation
agent is untouched.

### The inbound ordering agent

- **agent_id:** `agent_9501kv12skmjevpsq4g0pnd01z6b` (name: "sivra Quartermaster Ordering")
- LLM `gemini-2.5-flash`, voice **Charlotte** (`XB0fDUnXU5powFXDhCwa`), `eleven_turbo_v2` TTS.
- **Flow:** greet → ask what they want to buy → get an approximate budget (euros) +
  key details (brand/condition) → **read it back** → call `create_order` **once** →
  confirm "your team will get an update" → say goodbye → `end_call`.
- **Server (webhook) tool `create_order`** → `POST https://sivra.io/api/voice/intake`
  - **STATIC url, all data in the body** (no path templating — per the voice-tier
    memory: ElevenLabs webhook tools use a static URL with body fields).
  - header **`x-internal-token: $INTERNAL_API_TOKEN`** (same internal-auth scheme as
    the app's other `/api/internal/*` and `/api/voice/*` routes).
  - body: `{ callerPhone, title, description?, maxBudgetCents (integer cents),
    currency:"EUR" }`. `callerPhone` is bound to the built-in **`system__caller_id`**
    dynamic variable (the inbound SIP caller id), so the app resolves caller →
    user/org by phone; the agent only supplies the caller id + the fields it extracts.

> **`https://sivra.io/api/voice/intake` is the app's EVENTUAL home** — it is not live
> until `apps/web` is cut over to `sivra.io`. That's expected. The simulate test below
> proves the agent + tool today; true end-to-end ordering is validated after the app
> deploys. (Per ARCHITECTURE.md the endpoint is `POST /api/voice/intake`
> `{callerPhone, title, description?, maxBudgetCents?}`.)

### Inbound routing — one number does both directions

`+14472154920` (`phnum_5201kv0twb9cf3p901q4jds5t8tq`) now reports
`supports_inbound: true` **and** `supports_outbound: true`:

- **ElevenLabs side:** the SIP-trunk number was PATCHed to add an
  `inbound_trunk_config` (`allowed_addresses: ["0.0.0.0/0"]`, ACL-style — Telnyx
  forwards from its own IPs) and its **`assigned_agent`** set to the ordering agent.
  A phone number's `assigned_agent` is the **inbound-answering** agent.
- **Why outbound escalation still works:** the outbound-call API (`app.py`) passes its
  **own** `agent_id` (`agent_8501kv0…`, the escalation agent) and `agent_phone_number_id`
  in the request body, and authenticates to Telnyx with the SIP credential — it **never**
  consults the number's `assigned_agent`. So one number cleanly serves both:
  - **inbound** → answered by the number's `assigned_agent` (the ordering agent);
  - **outbound** → driven by the explicit `agent_id` in the `/call` request (the
    escalation agent).
- **Telnyx side — how an inbound PSTN call reaches ElevenLabs:** the number was
  **repointed** in Telnyx from the old "Quartermaster Voice (Gemini Live bridge)"
  connection to the FQDN SIP connection **`VoxGuard-intern`** (`2900679085086738176`),
  whose single FQDN is **`sip.rtc.elevenlabs.io:5060`**. So a call **to** `+14472154920`
  is delivered by Telnyx as a SIP INVITE to ElevenLabs, which hands it to the assigned
  ordering agent. (That same connection carries the `VoxGuard` outbound voice profile
  `2900274038037284437`, so it also routes ElevenLabs' **outbound** legs to the PSTN —
  inbound and outbound share it.)

> **Why not a "both directions on one ElevenLabs assignment" conflict?** ElevenLabs
> exposes a single `assigned_agent` per phone number (no separate inbound/outbound agent
> fields). That single assignment governs **inbound** answering only; outbound is chosen
> per-call by the `/v1/convai/sip-trunk/outbound-call` body. So assigning the ordering
> agent for inbound does **not** disturb outbound escalation. (The pre-existing
> inbound-only number `+14408209523` / `phnum_5601kj1…` was left as-is — not needed.)

### Provision it (idempotent)

```bash
# create/update the inbound ordering agent + create_order tool, verify the config
../.venv/bin/python provision_inbound.py
# + wire inbound routing (EL inbound_trunk_config + assign agent, and Telnyx repoint)
../.venv/bin/python provision_inbound.py --routing
```

Re-running updates the agent in place (set `EL_INBOUND_AGENT_ID`, now in `.env`) and
skips the Telnyx repoint if the number is already on the ElevenLabs FQDN connection.

### Verify the inbound agent WITHOUT calling anyone

```bash
../.venv/bin/python simulate_inbound.py   # reads EL_INBOUND_AGENT_ID from .env
```

A scripted caller says *"I need a cordless drill, budget about 100 euros, DeWalt if
possible."* ElevenLabs runs the text conversation; when the agent calls `create_order`,
simulate-conversation **mocks** the tool and reports the captured args. Verified result:

```
create_order params = {"title":"cordless drill","description":"DeWalt, new or refurbished",
                       "maxBudgetCents":10000,"currency":"EUR"}
```

The script asserts `title ~ drill`, `maxBudgetCents ~ 10000` (100 EUR in integer cents),
`currency == "EUR"`, DeWalt captured — all PASS. `callerPhone` is **not** in the
simulated args because it is **auto-injected from `system__caller_id` at webhook-dispatch
time** (it's not an LLM field), so the script asserts the **agent binding**
(`callerPhone.dynamic_variable == "system__caller_id"`) via a GET of the agent config.

### The ONE real inbound test (run by the USER — this service never calls the user)

This is the only step that places a live call, and **you** initiate it by calling in:

1. From any phone, **call `+14472154920`**.
2. The ordering agent answers: *"Hi! You've reached sivra procurement… What would you
   like to buy?"*
3. Say e.g. *"I need a cordless drill, budget about 100 euros, a DeWalt if possible."*
4. It reads the order back; confirm it. It then fires `create_order` to the app and
   says your team will get an update, then hangs up.

> Until the `apps/web` cutover, the `create_order` webhook target
> (`https://sivra.io/api/voice/intake`) is not live, so the tool call will not persist
> an order yet — the conversation still runs end-to-end. After the app deploys, the same
> call creates a real `Order` (caller resolved → user/org by phone).

### Inbound env vars

Appended to `.env` (resource ids, not secrets):

- `EL_INBOUND_AGENT_ID` — `agent_9501kv12skmjevpsq4g0pnd01z6b`
- `EL_PHONE_NUMBER_ID` — `phnum_5201kv0twb9cf3p901q4jds5t8tq` (shared in/outbound number)
- `TELNYX_SIP_CONN_ID` — `2900679085086738176` (VoxGuard-intern → `sip.rtc.elevenlabs.io`)
- `VOICE_INTAKE_BASE` (optional) — defaults to `https://sivra.io`; the `create_order`
  URL is baked into the agent at provision time.

## Verifying WITHOUT calling anyone

`simulate.py` proves the full loop with zero phone calls:

```bash
export EL_AGENT_ID=agent_8501kv0thytseyvs2tsb7sbyzaz7
.venv/bin/python simulate.py --resolution approve   # also: counter | decline
```

1. `POST https://sivra.io/escalate` → a real `request_id`.
2. `POST /v1/convai/agents/{agent_id}/simulate-conversation` with a scripted user
   who approves; ElevenLabs runs the text conversation and the agent calls
   `submit_decision` with the right args.
3. simulate-conversation **mocks** server tools (returns `"Tool Called."`), so the
   script then **replays the exact captured webhook POST** to `/resolve/{request_id}`
   — byte-for-byte what the agent fires on a real call — and confirms it via
   `GET /resolution/{request_id}`. (Verified: resolution lands with the decision +
   reward signal.)

## Config (env vars)

Read from env (`.env` locally; Railway service vars in prod):

- `ELEVEN_API_KEY` — ElevenLabs API key (`.env`)
- `EL_AGENT_ID` — `agent_8501kv0thytseyvs2tsb7sbyzaz7`
- `EL_PHONE_NUMBER_ID` — `phnum_5201kv0twb9cf3p901q4jds5t8tq`
- `PUBLIC_BASE_URL` — supervisor base (default `https://sivra.io`); the webhook tool's
  resolve URL is baked into the agent at provision time, not read at runtime.

## Live deployment (project "believable-comfort")

- **Service:** `elevenlabs-voice` (new, alongside `supervisor`/`voice`/`console`)
- **URL:** `https://elevenlabs-voice-production.up.railway.app`
- **Health:** `GET /health`
- Point the supervisor at it: set `VOICE_URL=https://elevenlabs-voice-production.up.railway.app`

## Deploy / redeploy

```bash
export RAILWAY_TOKEN=$(grep '^RAILWAY_API_KEY=' ../.env | cut -d= -f2-)   # project token
railway up --service elevenlabs-voice --detach
```

> `RAILWAY_API_KEY` in `.env` is a **project-scoped** token: it authorizes
> project-scoped ops (`status`, `up`, variables/domain via the GraphQL API with the
> `Project-Access-Token` header) but NOT account-scoped ones (`whoami`, `list`,
> `link`). The service + domain + vars were created via the Railway GraphQL API.

## The ONE real phone test (run by the user — this service never calls the user)

Everything above was verified without ringing anyone. To place the single real
outbound call, run this yourself with a number you want rung:

```bash
curl -s -X POST https://elevenlabs-voice-production.up.railway.app/call \
  -H "Content-Type: application/json" \
  -d '{
        "request_id": "PUT-A-REAL-REQUEST-ID-HERE",
        "to": "+4915204446662",
        "context": "Ready to buy a refurbished Bosch laser measure for 92 euros, 13 over the 79 cap. Approve, counter, or decline?",
        "person": "the procurement lead"
      }'
```

Get a real `request_id` first via `POST https://sivra.io/escalate` (a
`DecisionRequest`), so the agent's `submit_decision` resolves a real pending
delegation. A `200` with `"ok": true` and a `conversation_id` means the call was
placed; the human's phone rings and ElevenLabs runs the conversation.
```
```
