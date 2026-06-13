"""WhatsApp delivery via Twilio (tiers a/b).

Sends the delegation to the target person's WhatsApp number with tappable reply
options. Inbound replies arrive at a Twilio webhook that maps them to POST
/resolve (see delivery/whatsapp_webhook.py — next step).

Setup:
  1. Twilio account → WhatsApp Sandbox; each tester sends the join code to the
     sandbox number once (opt-in).
  2. Set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_WHATSAPP_FROM.
  3. Put each person's `whatsapp` number in config/org.yaml.

Raises on missing config so the dispatcher can fall back to the console stub.
"""
from __future__ import annotations

import os

import httpx

from delivery.base import TIER_EMOJI
from shared.contracts.schema import DecisionRequest, RoutingDecision
from supervisor import config

_REPLY_HINT = "\n\nReply  1=Approve · 2=Counter · 3=Decline   ·   rate: 👍 / 👎"


class WhatsAppDelivery:
    name = "whatsapp-twilio"

    def __init__(self) -> None:
        self.sid = os.environ["TWILIO_ACCOUNT_SID"]
        self.token = os.environ["TWILIO_AUTH_TOKEN"]
        self.frm = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
        self.api = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"

    def send(self, request: DecisionRequest, decision: RoutingDecision) -> None:
        to = config.whatsapp(request.org_id, decision.target_person)
        if not to:
            raise RuntimeError(f"no whatsapp number for {decision.target_person.value}")
        emoji = TIER_EMOJI.get(decision.urgency_tier.value, "💬")
        prefix = "🚨 [URGENT] " if decision.urgency_tier.value != "async" else ""
        # Voice tier still pings via WhatsApp here, with a call link appended later.
        body = f"{prefix}{emoji} {decision.suggested_message}{_REPLY_HINT}"
        to_addr = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        r = httpx.post(
            self.api,
            auth=(self.sid, self.token),
            data={"From": self.frm, "To": to_addr, "Body": body},
            timeout=10,
        )
        r.raise_for_status()
