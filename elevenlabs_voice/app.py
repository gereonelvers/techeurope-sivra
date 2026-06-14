"""sivra Voice Tier — ElevenLabs Conversational AI edition.

Replaces the flaky Gemini-Live/Telnyx hand-bridge. When an escalation is
urgent+complex (urgency_tier == "voice"), the supervisor hits POST /call here.
We place an ElevenLabs ConvAI **outbound call** (ElevenLabs -> Telnyx SIP trunk
-> PSTN) to the human, passing the pending decision as dynamic variables. The
agent explains the decision, captures approve/counter/decline + a feedback
signal, and calls its `submit_decision` webhook tool, which POSTs a
HumanResolution straight to the supervisor at {PUBLIC_BASE_URL}/resolve/{id}.
No media bridge, no Pipecat, no codec juggling — ElevenLabs runs the whole call.

Endpoints
  GET  /health   liveness + config sanity
  POST /call     {request_id, to, context, person} -> starts the outbound ConvAI call

Request/response contract is identical to the old voice service, so the
supervisor's existing POST {VOICE_URL}/call works by just repointing VOICE_URL.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Local .env first, then repo-root .env (dev only; Railway injects vars in prod).
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

EL_API = "https://api.elevenlabs.io"
EL_KEY = os.environ.get("ELEVEN_API_KEY", "")
# The provisioned ConvAI agent (see provision.py). Set as a Railway var in prod.
EL_AGENT_ID = os.environ.get("EL_AGENT_ID", "").strip()
# The imported outbound SIP-trunk phone number id in ElevenLabs (Telnyx +14472154920).
EL_PHONE_NUMBER_ID = os.environ.get("EL_PHONE_NUMBER_ID", "").strip()
SUPERVISOR_BASE = os.environ.get("PUBLIC_BASE_URL", "https://sivra.io").rstrip("/")

app = FastAPI(title="sivra Voice (ElevenLabs)", version="1.0.0")


def _el_headers() -> dict:
    return {"xi-api-key": EL_KEY, "Content-Type": "application/json"}


class CallRequest(BaseModel):
    """SAME contract as the old Gemini-Live voice service."""
    request_id: str
    to: str  # E.164, the human to call
    context: str  # the pending decision text (-> {{context}} dynamic variable)
    person: Optional[str] = "the procurement lead"  # -> {{person}}


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "sivra-voice-elevenlabs",
        "engine": "elevenlabs-convai",
        "supervisor": SUPERVISOR_BASE,
        "elevenlabs_configured": bool(EL_KEY),
        "agent_id": EL_AGENT_ID or None,
        "phone_number_id": EL_PHONE_NUMBER_ID or None,
        "telephony_ready": bool(EL_KEY and EL_AGENT_ID and EL_PHONE_NUMBER_ID),
    }


@app.post("/call")
async def place_call(req: CallRequest) -> JSONResponse:
    """Start an ElevenLabs ConvAI outbound call via the SIP trunk."""
    if not EL_KEY:
        return JSONResponse({"ok": False, "error": "ELEVEN_API_KEY not configured"}, status_code=500)
    if not EL_AGENT_ID:
        return JSONResponse({"ok": False, "error": "EL_AGENT_ID not configured"}, status_code=500)
    if not EL_PHONE_NUMBER_ID:
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "EL_PHONE_NUMBER_ID not configured — no outbound SIP-trunk phone number is "
                    "linked in ElevenLabs. See README (telephony / free-tier note)."
                ),
            },
            status_code=503,
        )
    if not req.to.startswith("+"):
        return JSONResponse({"ok": False, "error": "`to` must be E.164 (start with +)"}, status_code=422)

    person = req.person or "the procurement lead"
    payload = {
        "agent_id": EL_AGENT_ID,
        "agent_phone_number_id": EL_PHONE_NUMBER_ID,
        "to_number": req.to,
        "conversation_initiation_client_data": {
            "dynamic_variables": {
                "request_id": req.request_id,
                "context": req.context,
                "person": person,
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(
                f"{EL_API}/v1/convai/sip-trunk/outbound-call",
                headers=_el_headers(),
                json=payload,
            )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"elevenlabs call failed: {e}"}, status_code=502)

    body: Any
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = r.text[:600]
    if r.status_code >= 400:
        return JSONResponse(
            {"ok": False, "stage": "outbound-call", "status": r.status_code, "error": body},
            status_code=502,
        )
    # Mirror the old service's response shape (ok + ids), plus ElevenLabs ids.
    conv_id = body.get("conversation_id") if isinstance(body, dict) else None
    sip_id = body.get("sip_call_id") if isinstance(body, dict) else None
    return JSONResponse(
        {
            "ok": True,
            "to": req.to,
            "request_id": req.request_id,
            "conversation_id": conv_id,
            "sip_call_id": sip_id,
            "call_control_id": conv_id,  # back-compat alias for the old contract
            "elevenlabs": body,
        }
    )
