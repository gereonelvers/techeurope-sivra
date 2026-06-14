"""sivra · console — a small internal web console to test the live SMS + voice tiers.

A single HTML page (served at GET /) with four tools, each of which POSTs to a
thin server-side proxy here so secrets (Telnyx key) never touch the browser and
we sidestep CORS against sivra.io:

  POST /api/escalate   -> sivra.io/escalate           (SMS delegation)
  POST /api/call       -> escalate (voice tier) then voice/call   (phone call)
  POST /api/raw-sms    -> Telnyx /v2/messages          (arbitrary smoke SMS)
  GET  /api/pending    -> sivra.io/pending             (open delegations)

This service does NOT touch the supervisor/voice/agent code — it only calls their
public HTTP surfaces. It reads config from env (.env locally, Railway vars in prod).
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# Load local .env if present, then fall back to the repo-root .env (dev only;
# in prod these come from Railway service vars).
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from ui import render_page  # noqa: E402  (after load_dotenv so it's cheap either way)

SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "https://sivra.io").rstrip("/")
VOICE_URL = os.environ.get(
    "VOICE_URL", "https://voice-production-2b12.up.railway.app"
).rstrip("/")
TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY", "")
TELNYX_ALPHA_SENDER = os.environ.get("TELNYX_ALPHA_SENDER", "")
TELNYX_FROM = os.environ.get("TELNYX_FROM", "")
TELNYX_MESSAGING_PROFILE_ID = os.environ.get("TELNYX_MESSAGING_PROFILE_ID", "")
QM_DEMO_PHONE = os.environ.get("QM_DEMO_PHONE", "")

TELNYX_API = "https://api.telnyx.com/v2"

app = FastAPI(title="sivra console", version="0.1.0")


# ── request models (the page posts JSON) ─────────────────────────────────────
class EscalateBody(BaseModel):
    decision_type: str = "price_over_budget"
    situation_text: str
    title: Optional[str] = None
    listed_price: Optional[float] = None
    proposed_value: Optional[float] = None
    budget_cap: Optional[float] = None
    agent_confidence: float = 0.5
    marketplace: str = "site-a"
    agent_id: str = "buyer-console"


class CallBody(BaseModel):
    to: Optional[str] = None          # defaults to QM_DEMO_PHONE server-side
    context: Optional[str] = None     # optional override for Gemini's brief
    person: str = "the procurement lead"


class RawSmsBody(BaseModel):
    to: Optional[str] = None          # defaults to QM_DEMO_PHONE
    text: str


# ── helpers ──────────────────────────────────────────────────────────────────
def _demo_phone(supplied: Optional[str]) -> str:
    return (supplied or QM_DEMO_PHONE or "").strip()


def _decision_request(b: EscalateBody) -> dict[str, Any]:
    """Build a DecisionRequest payload (matches shared/contracts/schema.py)."""
    payload: dict[str, Any] = {
        "decision_type": b.decision_type,
        "situation_text": b.situation_text,
        "agent_id": b.agent_id,
        "marketplace": b.marketplace,
        "agent_confidence": b.agent_confidence,
    }
    if b.title:
        item: dict[str, Any] = {"title": b.title}
        if b.listed_price is not None:
            item["listed_price"] = b.listed_price
        payload["item"] = item
    if b.proposed_value is not None:
        payload["proposed_value"] = b.proposed_value
    if b.budget_cap is not None:
        payload["budget_cap"] = b.budget_cap
    return payload


def _reply_link(request_id: str) -> str:
    return f"{SUPERVISOR_URL}/d/{request_id[:6]}"


# ── page ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        render_page(
            supervisor_url=SUPERVISOR_URL,
            voice_url=VOICE_URL,
            demo_phone=QM_DEMO_PHONE,
            alpha_sender=TELNYX_ALPHA_SENDER or TELNYX_FROM,
        )
    )


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "sivra-console",
        "supervisor": SUPERVISOR_URL,
        "voice": VOICE_URL,
        "telnyx_configured": bool(TELNYX_API_KEY and (TELNYX_ALPHA_SENDER or TELNYX_FROM)),
        "demo_phone_set": bool(QM_DEMO_PHONE),
    }


# ── API: SMS delegation (escalate) ───────────────────────────────────────────
@app.post("/api/escalate")
def api_escalate(body: EscalateBody) -> JSONResponse:
    payload = _decision_request(body)
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{SUPERVISOR_URL}/escalate", json=payload)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"escalate failed: {e}"}, status_code=502)
    if r.status_code >= 400:
        return JSONResponse(
            {"ok": False, "status": r.status_code, "error": r.text[:600], "sent": payload},
            status_code=502,
        )
    decision = r.json()
    rid = decision.get("request_id", "")
    return JSONResponse(
        {
            "ok": True,
            "decision": decision,
            "reply_link": _reply_link(rid) if rid else None,
            "sms_sent": bool(decision.get("should_delegate")),
            "sent": payload,
        }
    )


# ── API: voice call (escalate to a voice-tier scenario, then dial) ───────────
@app.post("/api/call")
def api_call(body: CallBody) -> JSONResponse:
    to = _demo_phone(body.to)
    if not to.startswith("+"):
        return JSONResponse(
            {"ok": False, "error": "`to` must be E.164 (start with +). Set QM_DEMO_PHONE or pass a number."},
            status_code=422,
        )

    # 1) Create a real pending delegation the supervisor knows about, so the
    #    voice bridge can resolve it at /resolve/{request_id} after the call.
    #    We craft a scenario that the router will tag as the voice tier
    #    (a safety_flag with low confidence reliably needs a human sign-off).
    situation = (
        body.context
        or "Safety review: the seller is pushing for an off-platform cash handover "
        "tonight in an unfamiliar area, and the listing photos don't match the "
        "model. This needs a person to decide before we proceed."
    )
    escalate_payload = {
        "decision_type": "safety_flag",
        "situation_text": situation,
        "agent_id": "buyer-console",
        "marketplace": "site-a",
        "agent_confidence": 0.25,
        "item": {"title": "Used MacBook Pro 14\"", "listed_price": 1450.0},
        "proposed_value": 1450.0,
        "budget_cap": 1200.0,
    }
    try:
        with httpx.Client(timeout=30) as c:
            er = c.post(f"{SUPERVISOR_URL}/escalate", json=escalate_payload)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"escalate (for call) failed: {e}"}, status_code=502)
    if er.status_code >= 400:
        return JSONResponse(
            {"ok": False, "stage": "escalate", "status": er.status_code, "error": er.text[:600]},
            status_code=502,
        )
    decision = er.json()
    rid = decision.get("request_id", "")
    if not rid:
        return JSONResponse({"ok": False, "error": "escalate returned no request_id", "decision": decision}, status_code=502)

    # 2) Place the call referencing that request_id. Gemini's brief = the
    #    suggested message (or the caller's context override).
    call_payload = {
        "request_id": rid,
        "to": to,
        "context": body.context or decision.get("suggested_message") or situation,
        "person": body.person or "the procurement lead",
    }
    try:
        with httpx.Client(timeout=45) as c:
            cr = c.post(f"{VOICE_URL}/call", json=call_payload)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            {"ok": False, "stage": "call", "error": f"voice /call failed: {e}", "request_id": rid, "decision": decision},
            status_code=502,
        )
    body_json: Any
    try:
        body_json = cr.json()
    except Exception:  # noqa: BLE001
        body_json = cr.text[:600]
    ok = cr.status_code < 400 and isinstance(body_json, dict) and body_json.get("ok")
    return JSONResponse(
        {
            "ok": bool(ok),
            "stage": "call" if ok else "call_error",
            "request_id": rid,
            "decision": decision,
            "reply_link": _reply_link(rid),
            "call_status": cr.status_code,
            "call_result": body_json,
            "to": to,
        },
        status_code=200 if ok else 502,
    )


# ── API: raw SMS via Telnyx ──────────────────────────────────────────────────
@app.post("/api/raw-sms")
def api_raw_sms(body: RawSmsBody) -> JSONResponse:
    if not TELNYX_API_KEY:
        return JSONResponse({"ok": False, "error": "TELNYX_API_KEY not configured"}, status_code=500)
    to = _demo_phone(body.to)
    if not to.startswith("+"):
        return JSONResponse({"ok": False, "error": "`to` must be E.164 (start with +)"}, status_code=422)
    if not body.text.strip():
        return JSONResponse({"ok": False, "error": "text is empty"}, status_code=422)

    sender = TELNYX_ALPHA_SENDER or TELNYX_FROM
    payload: dict[str, Any] = {"from": sender, "to": to, "text": body.text}
    if TELNYX_MESSAGING_PROFILE_ID:
        payload["messaging_profile_id"] = TELNYX_MESSAGING_PROFILE_ID
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(
                f"{TELNYX_API}/messages",
                headers={"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"telnyx send failed: {e}"}, status_code=502)

    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = {"raw": r.text[:600]}
    if r.status_code >= 400:
        return JSONResponse({"ok": False, "status": r.status_code, "error": data}, status_code=502)
    # Trim the Telnyx response to the useful bits.
    d = data.get("data", {}) if isinstance(data, dict) else {}
    summary = {
        "id": d.get("id"),
        "from": (d.get("from") or {}).get("phone_number") if isinstance(d.get("from"), dict) else sender,
        "to": to,
        "text": body.text,
    }
    return JSONResponse({"ok": True, "summary": summary, "telnyx": data})


# ── API: pending delegations ─────────────────────────────────────────────────
@app.get("/api/pending")
def api_pending() -> JSONResponse:
    try:
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{SUPERVISOR_URL}/pending")
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"pending fetch failed: {e}"}, status_code=502)
    if r.status_code >= 400:
        return JSONResponse({"ok": False, "status": r.status_code, "error": r.text[:400]}, status_code=502)
    items = r.json()
    return JSONResponse({"ok": True, "count": len(items), "pending": items, "supervisor": SUPERVISOR_URL})
