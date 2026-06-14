"""Audit + receipts client — best-effort fleet telemetry to the app's internal API.

At key fleet milestones we append an OrderEvent (the append-only audit trail in
ARCHITECTURE.md "Flow") and, on completion, post the receipt/result. ALL of this
is:

  * guarded behind `APP_INTERNAL_URL` being set (no app configured -> no-op), and
  * best-effort / fire-and-forget: a failed POST is logged and swallowed so a flaky
    network NEVER blocks or kills the running mission.

Endpoints (header `x-internal-token: $INTERNAL_API_TOKEN`):
  POST {APP_INTERNAL_URL}/api/internal/orders/{orderId}/event
       {type, actorType: "agent"|"system", message?, data?}
  POST {APP_INTERNAL_URL}/api/internal/orders/{orderId}/result
       {resultItemId, resultTitle, resultPriceCents, receipt}

Milestone event types used by the fleet:
  search_started, agent_spawned, candidate_found, escalated, purchased, completed
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

APP_INTERNAL_URL = os.environ.get("APP_INTERNAL_URL", "").rstrip("/")
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

# Known milestone event types (documentation / typo-guard; not enforced).
EVENT_TYPES = (
    "search_started",
    "agent_spawned",
    "candidate_found",
    "escalated",
    "purchased",
    "completed",
)


def _app_internal_url() -> str:
    return (os.environ.get("APP_INTERNAL_URL") or APP_INTERNAL_URL or "").rstrip("/")


def _internal_token() -> str:
    return os.environ.get("INTERNAL_API_TOKEN") or INTERNAL_API_TOKEN or ""


def enabled() -> bool:
    """True iff audit/receipt posting is configured (APP_INTERNAL_URL set)."""
    return bool(_app_internal_url())


async def emit_event(
    order_id: Optional[str],
    type: str,
    *,
    actor_type: str = "system",
    message: Optional[str] = None,
    data: Optional[dict] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """Append one OrderEvent. Best-effort: returns True on a 2xx, False otherwise
    (including when disabled / no orderId). Never raises."""
    base = _app_internal_url()
    if not base or not order_id:
        return False
    body: dict[str, Any] = {"type": type, "actorType": actor_type}
    if message is not None:
        body["message"] = message
    if data is not None:
        body["data"] = data
    headers = {"x-internal-token": _internal_token()}
    url = f"{base}/api/internal/orders/{order_id}/event"

    owns = client is None
    c = client or httpx.AsyncClient(timeout=8.0)
    try:
        r = await c.post(url, json=body, headers=headers, timeout=8.0)
        return 200 <= r.status_code < 300
    except Exception:
        return False
    finally:
        if owns:
            await c.aclose()


async def post_result(
    order_id: Optional[str],
    *,
    result_item_id: Optional[Any] = None,
    result_title: Optional[str] = None,
    result_price_cents: Optional[int] = None,
    receipt: Optional[dict] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """Post the completion result/receipt. Best-effort; never raises."""
    base = _app_internal_url()
    if not base or not order_id:
        return False
    body: dict[str, Any] = {
        "resultItemId": result_item_id,
        "resultTitle": result_title,
        "resultPriceCents": result_price_cents,
        "receipt": receipt or {},
    }
    headers = {"x-internal-token": _internal_token()}
    url = f"{base}/api/internal/orders/{order_id}/result"

    owns = client is None
    c = client or httpx.AsyncClient(timeout=8.0)
    try:
        r = await c.post(url, json=body, headers=headers, timeout=8.0)
        return 200 <= r.status_code < 300
    except Exception:
        return False
    finally:
        if owns:
            await c.aclose()


def fire_event(
    order_id: Optional[str],
    type: str,
    *,
    actor_type: str = "system",
    message: Optional[str] = None,
    data: Optional[dict] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """Schedule an audit event without awaiting it (truly fire-and-forget).

    Safe to call from sync or async code: if an event loop is running we create a
    task; otherwise it's a no-op-safe best effort (skipped) so we never block.
    """
    if not enabled() or not order_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(
        emit_event(order_id, type, actor_type=actor_type, message=message,
                   data=data, client=client)
    )
