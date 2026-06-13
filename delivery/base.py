"""Delivery backend protocol. Each tier (local stub, Telegram, voice) implements
`send`. The supervisor's dispatcher picks one at runtime based on configured keys.
"""
from __future__ import annotations

from typing import Protocol

from shared.contracts.schema import DecisionRequest, RoutingDecision

TIER_EMOJI = {"async": "💬", "urgent_push": "🚨", "voice": "📞"}


class Delivery(Protocol):
    name: str

    def send(self, request: DecisionRequest, decision: RoutingDecision) -> None:
        """Deliver the delegation to the target person at the chosen urgency."""
        ...
