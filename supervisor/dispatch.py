"""Picks the delivery backend and sends the delegation.

Selection order: WhatsApp/Twilio (if TWILIO creds set) → local console stub. The
voice tier (tier c) is reached as a follow-up (a phone call bridged to Gemini
Live), so it isn't a separate top-level backend here.
"""
from __future__ import annotations

import functools
import os

from delivery.base import Delivery
from delivery.local_stub import LocalStubDelivery
from shared.contracts.schema import DecisionRequest, RoutingDecision


@functools.lru_cache(maxsize=1)
def get_delivery() -> Delivery:
    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
        try:
            from delivery.whatsapp import WhatsAppDelivery

            return WhatsAppDelivery()
        except Exception as e:  # pragma: no cover - falls back gracefully
            print(f"[dispatch] WhatsApp unavailable ({e}); using local stub.")
    return LocalStubDelivery()


def dispatch(request: DecisionRequest, decision: RoutingDecision) -> None:
    get_delivery().send(request, decision)
