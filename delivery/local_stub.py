"""Local stub delivery — prints the delegation to the console. Lets us run and
demo the full routing + reward loop with zero external accounts. Telegram/voice
backends implement the same interface and are selected when their keys exist.
"""
from __future__ import annotations

from delivery.base import TIER_EMOJI
from shared.contracts.schema import DecisionRequest, RoutingDecision
from supervisor import config


class LocalStubDelivery:
    name = "local-stub"

    def send(self, request: DecisionRequest, decision: RoutingDecision) -> None:
        person = decision.target_person
        who = config.label(request.org_id, person)
        emoji = TIER_EMOJI.get(decision.urgency_tier.value, "💬")
        tier = decision.urgency_tier.value.upper()
        bar = "─" * 72
        print(f"\n┌{bar}")
        print(f"│ {emoji}  DELEGATION → {who}  [{tier}]   (req {decision.request_id[:8]})")
        print(f"│ {decision.suggested_message}")
        print(f"│ why: {decision.rationale}")
        if decision.guardrail and decision.guardrail.needs_signoff:
            print(f"│ ⚠️  guardrail: binding commitment {decision.guardrail.commitments}")
        print(f"│ model: {decision.model_version}   extractor: "
              f"{decision.guardrail.extractor if decision.guardrail else 'n/a'}")
        print(f"└{bar}")
