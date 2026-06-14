"""Escalation client — the one place that talks to the human-in-the-loop backend.

Two interchangeable backends, selected at call time by env:

  * APP path (preferred, the new app's internal API): when `APP_INTERNAL_URL` is
    set we POST `{APP_INTERNAL_URL}/api/internal/escalations` (header
    `x-internal-token: $INTERNAL_API_TOKEN`) with a camelCase body the app
    persists, then poll `GET .../escalations/{requestId}/resolution` until the
    human answers (200) or we time out (404 while pending).

  * SUPERVISOR fallback (today's live flow): when `APP_INTERNAL_URL` is UNSET we
    keep the original behavior — POST `{SUPERVISOR_URL}/escalate` then poll
    `GET {SUPERVISOR_URL}/resolution/{requestId}`. Nothing about the current demo
    changes unless APP_INTERNAL_URL is configured.

Both return the SAME shape so agent_loop.py doesn't care which path ran:

    {request_id, decision, resolution|None, reply_url, timed_out, error, backend}

`decision` is the backend's immediate response (a RoutingDecision-ish dict);
`resolution` is the HumanResolution dict once the human replies (else None).

The request body the AGENT builds (shared/contracts/schema.py snake_case, e.g.
{agent_id, org_id, marketplace, decision_type, situation_text, proposed_value,
budget_cap, agent_confidence, item, order_id?}) is the canonical input; this
module maps it to whichever backend's wire format is needed. Kept dependency-light
(httpx only) so it imports cleanly anywhere the fleet runs.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable, Optional
from uuid import uuid4

import httpx

# ── config (read lazily so tests can monkeypatch env / module globals) ─────────
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "https://sivra.io").rstrip("/")
APP_INTERNAL_URL = os.environ.get("APP_INTERNAL_URL", "").rstrip("/")
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

ESCALATION_TIMEOUT_S = float(os.environ.get("ESCALATION_TIMEOUT_S", "180"))
ESCALATION_POLL_S = float(os.environ.get("ESCALATION_POLL_S", "2.5"))


def _eur_to_cents(v: Optional[float]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return None


def _app_internal_url() -> str:
    """Resolve APP_INTERNAL_URL at call time (env may be set after import)."""
    return (os.environ.get("APP_INTERNAL_URL") or APP_INTERNAL_URL or "").rstrip("/")


def _internal_token() -> str:
    return os.environ.get("INTERNAL_API_TOKEN") or INTERNAL_API_TOKEN or ""


def _supervisor_url() -> str:
    return (os.environ.get("SUPERVISOR_URL") or SUPERVISOR_URL or "").rstrip("/")


def use_app_backend() -> bool:
    """True iff the new app's internal API should be used (APP_INTERNAL_URL set)."""
    return bool(_app_internal_url())


# ── body mapping: agent snake_case DecisionRequest -> app camelCase ────────────
def to_app_escalation_body(request_body: dict, *, request_id: str) -> dict:
    """Map a snake_case DecisionRequest dict to the app's internal escalations body.

    App contract (ARCHITECTURE.md "App API surface"):
      {requestId, orgId, orderId, decisionType, situationText,
       proposedValueCents, budgetCapCents, agentConfidence, item}
    Money is integer cents at the app boundary; the agent carries EUR floats.
    """
    item = request_body.get("item")
    return {
        "requestId": request_id,
        "orgId": request_body.get("org_id"),
        "orderId": request_body.get("order_id"),
        "decisionType": request_body.get("decision_type"),
        "situationText": request_body.get("situation_text"),
        "proposedValueCents": _eur_to_cents(request_body.get("proposed_value")),
        "budgetCapCents": _eur_to_cents(request_body.get("budget_cap")),
        "agentConfidence": request_body.get("agent_confidence"),
        "item": item,
    }


async def _maybe_call(cb: Optional[Callable[..., Any]], *args) -> None:
    if cb is None:
        return
    try:
        maybe = cb(*args)
        if asyncio.iscoroutine(maybe):
            await maybe
    except Exception:
        pass


# ── APP backend ────────────────────────────────────────────────────────────────
async def _escalate_via_app(
    client: httpx.AsyncClient,
    request_body: dict,
    *,
    timeout_s: float,
    poll_s: float,
    on_routed: Optional[Callable[[dict], Any]],
    on_poll: Optional[Callable[[], Any]],
) -> dict:
    base = _app_internal_url()
    headers = {"x-internal-token": _internal_token()}
    out: dict = {"request_id": None, "decision": None, "resolution": None,
                 "reply_url": None, "timed_out": False, "error": None,
                 "backend": "app"}

    # The app persists by requestId; generate one so the POST + poll agree even if
    # the app echoes nothing useful.
    request_id = request_body.get("request_id") or uuid4().hex
    out["request_id"] = request_id
    body = to_app_escalation_body(request_body, request_id=request_id)

    try:
        resp = await client.post(
            f"{base}/api/internal/escalations", json=body, headers=headers, timeout=20.0
        )
        resp.raise_for_status()
        decision = resp.json() if resp.content else {}
    except Exception as e:
        out["error"] = f"app-escalate-failed: {e}"
        return out

    # The app may echo its own requestId; honor it for the poll.
    rid = decision.get("requestId") or decision.get("request_id") or request_id
    out["request_id"] = rid
    out["decision"] = decision
    out["reply_url"] = decision.get("replyUrl") or (
        f"{base}/d/{rid[:6]}" if rid else None
    )
    await _maybe_call(on_routed, out)

    deadline = time.time() + timeout_s
    res_url = f"{base}/api/internal/escalations/{rid}/resolution"
    while time.time() < deadline:
        await _maybe_call(on_poll)
        try:
            r = await client.get(res_url, headers=headers, timeout=10.0)
            if r.status_code == 200:
                out["resolution"] = r.json()
                return out
            # 404 => not resolved yet; keep polling.
        except Exception:
            pass
        await asyncio.sleep(poll_s)

    out["timed_out"] = True
    return out


# ── SUPERVISOR fallback (today's behavior) ─────────────────────────────────────
async def _escalate_via_supervisor(
    client: httpx.AsyncClient,
    request_body: dict,
    *,
    timeout_s: float,
    poll_s: float,
    on_routed: Optional[Callable[[dict], Any]],
    on_poll: Optional[Callable[[], Any]],
) -> dict:
    base = _supervisor_url()
    out: dict = {"request_id": None, "decision": None, "resolution": None,
                 "reply_url": None, "timed_out": False, "error": None,
                 "backend": "supervisor"}
    try:
        resp = await client.post(f"{base}/escalate", json=request_body, timeout=20.0)
        resp.raise_for_status()
        decision = resp.json()
    except Exception as e:
        out["error"] = f"escalate-failed: {e}"
        return out

    rid = decision.get("request_id")
    out["request_id"] = rid
    out["decision"] = decision
    # short link code used by the SMS reply page: /d/{request_id[:6]}
    out["reply_url"] = f"{base}/d/{rid[:6]}" if rid else None
    await _maybe_call(on_routed, out)

    if not rid:
        return out

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        await _maybe_call(on_poll)
        try:
            r = await client.get(f"{base}/resolution/{rid}", timeout=10.0)
            if r.status_code == 200:
                out["resolution"] = r.json()
                return out
            # 404 => not resolved yet; keep polling
        except Exception:
            pass
        await asyncio.sleep(poll_s)

    out["timed_out"] = True
    return out


# ── public entrypoint ──────────────────────────────────────────────────────────
async def escalate(
    client: httpx.AsyncClient,
    request_body: dict,
    *,
    timeout_s: float = ESCALATION_TIMEOUT_S,
    poll_s: float = ESCALATION_POLL_S,
    on_routed: Optional[Callable[[dict], Any]] = None,
    on_poll: Optional[Callable[[], Any]] = None,
) -> dict:
    """Escalate one decision and BLOCK on the human's resolution (or timeout).

    Routes to the app internal API when APP_INTERNAL_URL is set, else the
    supervisor (back-compat). Returns a backend-agnostic dict:
        {request_id, decision, resolution|None, reply_url, timed_out, error, backend}

    on_routed(out) fires once after the POST (so a dashboard can flip the tile to
    `escalated`); on_poll() fires each poll tick (keepalive). Both may be sync or
    async; exceptions in them are swallowed.
    """
    if use_app_backend():
        return await _escalate_via_app(
            client, request_body, timeout_s=timeout_s, poll_s=poll_s,
            on_routed=on_routed, on_poll=on_poll,
        )
    return await _escalate_via_supervisor(
        client, request_body, timeout_s=timeout_s, poll_s=poll_s,
        on_routed=on_routed, on_poll=on_poll,
    )
