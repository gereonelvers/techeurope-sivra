"""Quartermaster Voice Tier — telephony <-> Gemini Live bridge.

When an escalation is urgent+complex (urgency_tier == "voice"), the supervisor
hits POST /call here. We place a real Telnyx Call Control outbound call to the
human, and when they answer we bidirectionally stream the call audio (8 kHz
mu-law) into a Gemini Live native-audio session via Pipecat. Gemini explains the
pending decision, answers questions, and — when the human gives a clear answer —
calls the `resolve_decision` tool, which POSTs the HumanResolution back to the
supervisor at {PUBLIC_BASE_URL}/resolve/{request_id} and ends the call.

Endpoints
  GET  /health         liveness + config sanity
  POST /call           {request_id, to, context} -> dials the human
  POST /telnyx/voice   Telnyx Call Control webhook (call.answered/hangup/...)
  WS   /media          Telnyx <-> Gemini Live media bridge (one socket per call)

Bridge: Pipecat 1.3.0 — TelnyxFrameSerializer (mu-law<->PCM transcode + turn
handling) + GeminiLiveLLMService (native audio). See test_gemini_live.py for the
isolated Gemini check and setup_telnyx_voice.py for Telnyx provisioning.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY", "")
TELNYX_FROM = os.environ.get("TELNYX_FROM", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Where to POST the resolved decision (the deployed supervisor / sivra.io).
SUPERVISOR_BASE = os.environ.get("PUBLIC_BASE_URL", "https://sivra.io").rstrip("/")
# This service's own public https/wss origin (Railway domain or tunnel). Used to
# build the wss://.../media stream URL Telnyx connects back to.
PUBLIC_VOICE_URL = os.environ.get("PUBLIC_VOICE_URL", "").rstrip("/")
# Call Control Application id (== connection_id). Auto-discovered at boot if unset.
CALL_CONTROL_APP_ID = os.environ.get("CALL_CONTROL_APP_ID", "")
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Charon")

TELNYX_API = "https://api.telnyx.com/v2"
APP_NAME = "Quartermaster Voice (Gemini Live bridge)"

# call_control_id -> {"request_id":..., "context":..., "to":..., "person":...}
CALLS: dict[str, dict] = {}

app = FastAPI(title="Quartermaster Voice", version="0.1.0")


# ── Telnyx REST helpers ─────────────────────────────────────────────────────
async def _telnyx(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as c:
        return await c.request(
            method,
            f"{TELNYX_API}{path}",
            headers={"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"},
            **kw,
        )


async def discover_connection_id() -> str:
    """Find our Call Control Application id by name (idempotent provisioning)."""
    global CALL_CONTROL_APP_ID
    if CALL_CONTROL_APP_ID:
        return CALL_CONTROL_APP_ID
    r = await _telnyx("GET", "/call_control_applications", params={"page[size]": 250})
    r.raise_for_status()
    for a in r.json().get("data", []):
        if a.get("application_name") == APP_NAME:
            CALL_CONTROL_APP_ID = a["id"]
            logger.info(f"discovered Call Control App / connection_id={CALL_CONTROL_APP_ID}")
            return CALL_CONTROL_APP_ID
    raise RuntimeError(
        "No Call Control Application found. Run setup_telnyx_voice.py first "
        "or set CALL_CONTROL_APP_ID."
    )


def _media_ws_url() -> str:
    if not PUBLIC_VOICE_URL:
        raise RuntimeError("PUBLIC_VOICE_URL not set — cannot build wss media URL")
    return PUBLIC_VOICE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/media"


# ── Models ──────────────────────────────────────────────────────────────────
class CallRequest(BaseModel):
    request_id: str
    to: str  # E.164, the human to call
    context: str  # the pending decision text (Gemini's system instruction body)
    person: Optional[str] = "the manager"  # who we're addressing on the phone


# ── Routes ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "quartermaster-voice",
        "supervisor": SUPERVISOR_BASE,
        "public_voice_url": PUBLIC_VOICE_URL or None,
        "connection_id": CALL_CONTROL_APP_ID or None,
        "telnyx_configured": bool(TELNYX_API_KEY and TELNYX_FROM),
        "gemini_configured": bool(GEMINI_API_KEY),
        "active_calls": len(CALLS),
    }


@app.post("/call")
async def place_call(req: CallRequest):
    """Place an outbound Telnyx Call Control call to the human."""
    if not (TELNYX_API_KEY and TELNYX_FROM):
        return JSONResponse({"error": "TELNYX_API_KEY/TELNYX_FROM not configured"}, status_code=500)
    if not req.to.startswith("+"):
        return JSONResponse({"error": "`to` must be E.164 (start with +)"}, status_code=422)
    try:
        connection_id = await discover_connection_id()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"no call control app: {e}"}, status_code=500)

    payload = {
        "connection_id": connection_id,
        "to": req.to,
        "from": TELNYX_FROM,
        # We start media streaming on call.answered (see /telnyx/voice) so we can
        # bind the websocket to this specific call_control_id.
    }
    r = await _telnyx("POST", "/calls", json=payload)
    if r.status_code >= 400:
        logger.error(f"telnyx dial failed {r.status_code}: {r.text}")
        return JSONResponse({"error": "telnyx dial failed", "detail": r.text}, status_code=502)
    data = r.json()["data"]
    ccid = data["call_control_id"]
    CALLS[ccid] = {
        "request_id": req.request_id,
        "context": req.context,
        "to": req.to,
        "person": req.person or "the manager",
    }
    logger.info(f"placed call to {req.to} ccid={ccid} request_id={req.request_id}")
    return {"ok": True, "call_control_id": ccid, "call_leg_id": data.get("call_leg_id"), "to": req.to}


@app.post("/telnyx/voice")
async def telnyx_webhook(request: Request):
    """Telnyx Call Control webhook. Start media stream on answer, clean up on hangup."""
    body = await request.json()
    event = body.get("data", {})
    etype = event.get("event_type")
    payload = event.get("payload", {})
    ccid = payload.get("call_control_id")
    logger.info(f"telnyx webhook: {etype} ccid={ccid}")

    if etype == "call.answered" and ccid:
        # Start bidirectional media streaming to our /media websocket.
        try:
            stream_url = _media_ws_url()
        except Exception as e:  # noqa: BLE001
            logger.error(f"cannot stream: {e}")
            return {"ok": False}
        r = await _telnyx(
            "POST",
            f"/calls/{ccid}/actions/streaming_start",
            json={
                "stream_url": stream_url,
                "stream_track": "both_tracks",
                "stream_bidirectional_mode": "rtp",
                "stream_bidirectional_codec": "PCMU",  # 8 kHz mu-law both ways
            },
        )
        if r.status_code >= 400:
            logger.error(f"streaming_start failed {r.status_code}: {r.text}")
        else:
            logger.info(f"streaming_start -> {stream_url} for {ccid}")

    elif etype in ("call.hangup", "call.machine.detection.ended") and ccid:
        CALLS.pop(ccid, None)

    return {"ok": True}


@app.websocket("/media")
async def media(ws: WebSocket):
    """Bridge Telnyx media <-> Gemini Live for the lifetime of one call."""
    await ws.accept()
    try:
        await _run_bridge(ws)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"media bridge error: {e}")
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


async def _resolve_to_supervisor(request_id: str, resolution: str, value: Optional[float], notes: str) -> dict:
    """POST the human's decision back to the supervisor."""
    payload = {
        "request_id": request_id,
        "resolution": resolution,  # approve|counter|decline
        "rating": "good",
        "resolved_by": "manager",
    }
    if value is not None:
        payload["value"] = value
    if notes:
        payload["notes"] = notes
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{SUPERVISOR_BASE}/resolve/{request_id}", json=payload)
    logger.info(f"resolve -> {SUPERVISOR_BASE}/resolve/{request_id} [{r.status_code}] {payload}")
    return {"status": r.status_code, "body": r.text[:300]}


async def _run_bridge(ws: WebSocket) -> None:
    # Imports kept local so /health and /call work even if pipecat isn't importable.
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.runner.utils import parse_telephony_websocket
    from pipecat.serializers.telnyx import TelnyxFrameSerializer
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    transport_type, call_data = await parse_telephony_websocket(ws)
    logger.info(f"/media start: type={transport_type} data={ {k: call_data.get(k) for k in ('stream_id','call_control_id','from','to')} }")

    ccid = call_data["call_control_id"]
    stream_id = call_data["stream_id"]
    out_enc = call_data.get("outbound_encoding", "PCMU")
    info = CALLS.get(ccid, {})
    request_id = info.get("request_id")
    context = info.get("context", "a pending purchase decision")
    person = info.get("person", "the manager")

    serializer = TelnyxFrameSerializer(
        stream_id=stream_id,
        outbound_encoding=out_enc,
        inbound_encoding="PCMU",
        call_control_id=ccid,
        api_key=TELNYX_API_KEY,
    )

    transport = FastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
        ),
    )

    system_instruction = (
        f"You are phoning {person} on behalf of an autonomous buyer agent. "
        f"Pending decision: {context} "
        "Greet them briefly, explain the decision in one or two sentences, and answer any "
        "questions plainly. Your goal is a clear decision: approve, counter (with a specific "
        "euro amount), or decline. Once they decide, read it back to confirm, then call the "
        "resolve_decision tool with their choice. Speak naturally and keep it short — this is a "
        "phone call. After the tool call, thank them and say goodbye."
    )

    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="resolve_decision",
            description=(
                "Record the human's final decision on the pending purchase. Call this exactly "
                "once, after they clearly approve, counter, or decline and you've confirmed it."
            ),
            properties={
                "resolution": {
                    "type": "string",
                    "enum": ["approve", "counter", "decline"],
                    "description": "The human's decision.",
                },
                "value": {
                    "type": "number",
                    "description": "The counter amount in euros (only for resolution=counter).",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional short note / reason from the human.",
                },
            },
            required=["resolution"],
        )
    ])

    llm = GeminiLiveLLMService(
        api_key=GEMINI_API_KEY,
        voice_id=GEMINI_VOICE,
        system_instruction=system_instruction,
        tools=tools,
        model=os.getenv("GEMINI_LIVE_MODEL", "models/gemini-2.5-flash-native-audio-preview-12-2025"),
    )

    resolved = asyncio.Event()

    async def resolve_decision(params):
        args = params.arguments or {}
        resolution = str(args.get("resolution", "")).lower().strip()
        if resolution not in ("approve", "counter", "decline"):
            await params.result_callback({"error": "resolution must be approve|counter|decline"})
            return
        value = args.get("value")
        try:
            value = float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        notes = str(args.get("notes", "") or "")
        result = {"recorded": True}
        if request_id:
            try:
                result = await _resolve_to_supervisor(request_id, resolution, value, notes)
            except Exception as e:  # noqa: BLE001
                logger.error(f"resolve POST failed: {e}")
                result = {"error": str(e)}
        else:
            logger.warning(f"no request_id for ccid={ccid}; decision not forwarded: {resolution} {value}")
        await params.result_callback({"ok": True, "supervisor": result})
        # Let Gemini say goodbye, then end the call shortly after.
        async def _end():
            await asyncio.sleep(6)
            resolved.set()
            await task.queue_frame(EndFrame())
        asyncio.create_task(_end())

    llm.register_function("resolve_decision", resolve_decision)

    pipeline = Pipeline([
        transport.input(),
        llm,
        transport.output(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            allow_interruptions=True,
        ),
    )

    @transport.event_handler("on_client_disconnected")
    async def _on_disc(_t, _c):  # noqa: ANN001
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    logger.info(f"bridge running for request_id={request_id} ccid={ccid}")
    await runner.run(task)
    CALLS.pop(ccid, None)
    logger.info(f"bridge finished ccid={ccid} resolved={resolved.is_set()}")


@app.on_event("startup")
async def _startup():
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))
    if TELNYX_API_KEY:
        try:
            await discover_connection_id()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"connection_id not discovered at boot: {e}")
    logger.info(
        f"voice service up | supervisor={SUPERVISOR_BASE} | public_voice_url={PUBLIC_VOICE_URL or '(unset)'}"
    )
