"""Picks the delivery backend and sends the delegation.

Selection order: Telnyx SMS (if TELNYX_API_KEY + TELNYX_FROM set) → local console
stub. For the voice tier (urgency_tier == voice) we ALSO trigger a phone call via
the voice service (VOICE_URL) — it bridges the call to Gemini Live and resolves the
delegation itself. VOICE_URL is set only on the deployed service, so local test
runs never place real calls. Delivery/voice failures never break escalation.
"""
from __future__ import annotations

import functools
import os

import httpx

from delivery.base import Delivery
from delivery.local_stub import LocalStubDelivery
from shared.contracts.schema import DecisionRequest, RoutingDecision, UrgencyTier
from supervisor import config


@functools.lru_cache(maxsize=1)
def get_delivery() -> Delivery:
    if os.getenv("TELNYX_API_KEY") and os.getenv("TELNYX_FROM"):
        try:
            from delivery.telnyx import TelnyxSMSDelivery

            return TelnyxSMSDelivery()
        except Exception as e:  # pragma: no cover - falls back gracefully
            print(f"[dispatch] Telnyx unavailable ({e}); using local stub.")
    return LocalStubDelivery()


def _maybe_voice_call(request: DecisionRequest, decision: RoutingDecision) -> None:
    if decision.urgency_tier != UrgencyTier.voice:
        return
    voice_url = os.getenv("VOICE_URL")
    to = config.phone(request.org_id, decision.target_person)
    if not voice_url or not to:
        return
    try:
        httpx.post(
            f"{voice_url.rstrip('/')}/call",
            json={
                "request_id": request.request_id,
                "to": to,
                "context": decision.suggested_message,
                "person": config.label(request.org_id, decision.target_person),
            },
            timeout=10,
        )
    except Exception as e:  # pragma: no cover
        print(f"[dispatch] voice call failed ({e})")


def dispatch(request: DecisionRequest, decision: RoutingDecision) -> None:
    try:
        get_delivery().send(request, decision)
    except Exception as e:  # pragma: no cover - escalation must survive delivery errors
        print(f"[dispatch] delivery failed ({e}); decision still recorded.")
    _maybe_voice_call(request, decision)
