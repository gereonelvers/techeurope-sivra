# Quartermaster Voice Tier

Telephony ↔ **Gemini Live (native audio)** bridge for the `urgency_tier == "voice"`
escalation path. When a decision is urgent **and** complex, the supervisor asks
this service to place a real phone call to the human. We dial them via Telnyx
Call Control, bidirectionally stream the call audio (8 kHz μ-law) into a Gemini
Live native-audio session, let them talk the decision through, capture their
**approve / counter / decline**, and POST it back to the supervisor at
`{PUBLIC_BASE_URL}/resolve/{request_id}`.

The bridge is built on **Pipecat 1.3.0** (`TelnyxFrameSerializer` for the
μ-law↔PCM transcode + turn-taking, `GeminiLiveLLMService` for native audio).

## Files

```
voice/
├── app.py                 FastAPI + websocket service (POST /call, /telnyx/voice, WS /media)
├── setup_telnyx_voice.py  Idempotent Telnyx Call Control App provisioning
├── test_gemini_live.py    Standalone Gemini Live smoke test (no telephony)
├── Dockerfile             python:3.12-slim + ffmpeg/libgomp for the audio stack
├── railway.json           Railway build/deploy config (Dockerfile builder)
├── requirements.txt       Pinned deps (verified on Python 3.12)
├── .dockerignore / .railwayignore
└── .venv/                 local venv (NOT the repo-root .venv)
```

## Live deployment (project "believable-comfort")

- **Service:** `voice` (new service, separate from `supervisor`)
- **URL:** `https://voice-production-2b12.up.railway.app`
- **Telnyx Call Control App id / connection_id:** `2981381885642409012`
  - webhook → `https://voice-production-2b12.up.railway.app/telnyx/voice`
  - `TELNYX_FROM` (+14472154920) assigned to it; outbound voice profile attached
- **Health:** `GET https://voice-production-2b12.up.railway.app/health`

Service env vars set on Railway: `TELNYX_API_KEY`, `TELNYX_FROM`, `GEMINI_API_KEY`,
`PUBLIC_BASE_URL=https://sivra.io`, `PUBLIC_VOICE_URL=<this service url>`,
`CALL_CONTROL_APP_ID=2981381885642409012`.

## The hook the supervisor should call (for `urgency_tier == "voice"`)

```
POST https://voice-production-2b12.up.railway.app/call
Content-Type: application/json

{
  "request_id": "<the pending delegation's request_id>",
  "to":         "+49...",                 // E.164 of the human to call
  "context":    "<decision.suggested_message>",  // becomes Gemini's brief
  "person":     "the procurement lead"     // optional, how Gemini addresses them
}
```

Returns `{ "ok": true, "call_control_id": "...", "to": "..." }` once Telnyx
accepts the dial. The bridge then resolves the delegation itself by calling
`POST {PUBLIC_BASE_URL}/resolve/{request_id}` with
`{resolution, value?, rating:"good", resolved_by:"manager"}` when the human
decides — so the supervisor's existing `GET /resolution/{id}` polling just works.

## Trigger a real end-to-end call

1. Create / pick a pending delegation to get a `request_id` (e.g. via the
   supervisor `POST /escalate`, or use a real pending one from `GET /pending`).
2. Fire the hook above with the human's number in `to`.
3. The human's phone rings; on answer, Gemini greets them, explains the pending
   decision, answers questions, confirms a decision, and ends the call.
4. The buyer agent's `GET {PUBLIC_BASE_URL}/resolution/{request_id}` now returns
   the human's choice.

```bash
curl -s -X POST https://voice-production-2b12.up.railway.app/call \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"<RID>","to":"+49XXXXXXXXXXX",
       "context":"Seller wants €340 — €20 over your €320 cap. Approve, counter, or decline?",
       "person":"the procurement lead"}'
```

## What was verified live vs. scaffolded

Verified **live** (real call to the test number):
- Service boots; `/call` validates input and dials via Telnyx Call Control.
- Telnyx call lifecycle fired: `call.initiated → call.answered → streaming.started`.
- Pipecat parsed the Telnyx media handshake (`stream_id`, `call_control_id`,
  μ-law encoding) and the **Gemini Live native-audio session connected** with the
  decision as its system instruction. Audio streamed bidirectionally; the call
  stayed up as a live conversation, then tore down cleanly on hangup.
- Gemini Live half independently verified by `test_gemini_live.py` (received
  24 kHz PCM audio + transcript).
- The `resolve_decision → POST /resolve/{id}` loop verified end-to-end against
  the live supervisor (delegation moved to resolved; `GET /resolution/{id}` returns it).

Not self-verifiable headlessly (needs a human on the line):
- A human actually *speaking* "approve/counter/decline" so Gemini calls the
  `resolve_decision` tool during a live call. That code path is wired and the
  downstream POST is proven; only the in-call human utterance is unverified.

## Re-provisioning Telnyx (idempotent)

```bash
.venv/bin/python setup_telnyx_voice.py \
  --webhook-base https://voice-production-2b12.up.railway.app
```
Finds-or-creates the Call Control App, attaches an outbound voice profile (needed
or Telnyx returns error D38), and assigns `TELNYX_FROM`. Safe to re-run.

## Local dev (behind a tunnel)

Telnyx needs a public `https`/`wss` URL. Locally:
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
cloudflared tunnel --url http://localhost:8000          # -> https://<random>.trycloudflare.com
PUBLIC_VOICE_URL=https://<random>.trycloudflare.com .venv/bin/uvicorn app:app ...
.venv/bin/python setup_telnyx_voice.py --webhook-base https://<random>.trycloudflare.com
```
Set `PUBLIC_VOICE_URL` to the tunnel URL so `/media` advertises the right `wss`.
```
```

## Notes / gotchas

- A Telnyx Call Control connection needs an **Outbound Voice Profile** or dials
  fail with error **D38**. `setup_telnyx_voice.py` attaches one automatically.
- Bidirectional WS audio uses `stream_bidirectional_mode: "rtp"` +
  `stream_bidirectional_codec: "PCMU"` with `stream_track: "both_tracks"` — both
  directions ride the *same* websocket as base64 `media` frames (the "rtp" naming
  is misleading; it is **not** a separate UDP socket).
- Single Railway worker on purpose: the in-process `CALLS` map and the websocket
  bridge must share state.
