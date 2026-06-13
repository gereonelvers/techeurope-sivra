"""Picks the delivery backend and sends the delegation.

Selection order: Telnyx SMS (if TELNYX_API_KEY + TELNYX_FROM set) → local console
stub. The voice tier (tier c) is reached as a follow-up (a Telnyx Call Control
call bridged to Gemini Live), so it isn't a separate top-level backend here.

Delivery failures never break escalation — the decision is still recorded.
"""
from __future__ import annotations

import functools
import os

from delivery.base import Delivery
from delivery.local_stub import LocalStubDelivery
from shared.contracts.schema import DecisionRequest, RoutingDecision


@functools.lru_cache(maxsize=1)
def get_delivery() -> Delivery:
    if os.getenv("TELNYX_API_KEY") and os.getenv("TELNYX_FROM"):
        try:
            from delivery.telnyx import TelnyxSMSDelivery

            return TelnyxSMSDelivery()
        except Exception as e:  # pragma: no cover - falls back gracefully
            print(f"[dispatch] Telnyx unavailable ({e}); using local stub.")
    return LocalStubDelivery()


def dispatch(request: DecisionRequest, decision: RoutingDecision) -> None:
    try:
        get_delivery().send(request, decision)
    except Exception as e:  # pragma: no cover - escalation must survive delivery errors
        print(f"[dispatch] delivery failed ({e}); decision still recorded.")
