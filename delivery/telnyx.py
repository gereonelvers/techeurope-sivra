"""Telnyx SMS delivery (tiers a/b).

Sends the delegation as an SMS to the target person's phone with numbered reply
options. Inbound replies hit a Telnyx webhook → POST /resolve (see
delivery/telnyx_webhook.py — next step). The voice tier (tier c) uses Telnyx
Call Control + WebSocket media streaming bridged to Gemini Live (task 8).

Needs TELNYX_API_KEY + TELNYX_FROM (an E.164 Telnyx number) and per-person
`phone` numbers in config/org.yaml. Raises on missing config so the dispatcher
falls back to the console stub.
"""
from __future__ import annotations

import os

import httpx

from delivery.base import TIER_EMOJI
from shared.contracts.schema import DecisionRequest, RoutingDecision
from supervisor import config

_API = "https://api.telnyx.com/v2/messages"


class TelnyxSMSDelivery:
    name = "telnyx-sms"

    def __init__(self) -> None:
        self.key = os.environ["TELNYX_API_KEY"]
        # International A2P (e.g. US long code -> DE) needs an alphanumeric sender;
        # prefer it when set, else send from the raw number.
        self.frm = os.getenv("TELNYX_ALPHA_SENDER") or os.environ["TELNYX_FROM"]
        self.profile = os.getenv("TELNYX_MESSAGING_PROFILE_ID")

    def send(self, request: DecisionRequest, decision: RoutingDecision) -> None:
        to = config.phone(request.org_id, decision.target_person)
        if not to:
            raise RuntimeError(f"no phone number for {decision.target_person.value}")
        emoji = TIER_EMOJI.get(decision.urgency_tier.value, "")
        prefix = "[URGENT] " if decision.urgency_tier.value != "async" else ""
        base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        link = f"{base}/d/{request.request_id[:6]}"
        body = f"{prefix}{emoji} {decision.suggested_message}\n→ {link}"
        payload = {"from": self.frm, "to": to, "text": body}
        if self.profile:
            payload["messaging_profile_id"] = self.profile
        r = httpx.post(
            _API,
            headers={"Authorization": f"Bearer {self.key}"},
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
