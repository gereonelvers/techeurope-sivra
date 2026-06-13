"""Delegation router — decides *whether* to involve a human, *which* person, and
*how loudly*.

v0 is transparent rules. It doubles as (a) the bootstrap labeling logic for the
synthetic dataset and (b) the always-available fallback. A Pioneer-fine-tuned
model plugs in behind the same `route()` signature (see pioneer/router_client.py)
once it's trained — at which point this becomes the comparison baseline.
"""
from __future__ import annotations

from shared.contracts.schema import (
    DecisionRequest,
    DecisionType,
    Guardrail,
    RoutingDecision,
    TargetPerson,
    UrgencyTier,
)
from supervisor import config

VOICE_OVERAGE_RATIO = 1.5
LOW_CONFIDENCE = 0.6
VERY_LOW_CONFIDENCE = 0.4

_ALWAYS_DELEGATE = {
    DecisionType.safety_flag,
    DecisionType.approve_purchase,
    DecisionType.ambiguous_listing,
}


def _amount(req: DecisionRequest) -> float:
    if req.proposed_value:
        return float(req.proposed_value)
    if req.item and req.item.listed_price:
        return float(req.item.listed_price)
    return 0.0


def _over_budget(req: DecisionRequest) -> bool:
    return bool(req.proposed_value and req.budget_cap and req.proposed_value > req.budget_cap)


def _should_delegate(req: DecisionRequest, g: Guardrail) -> bool:
    if g.needs_signoff:
        return True
    if req.decision_type in _ALWAYS_DELEGATE:
        return True
    if _over_budget(req):
        return True
    if req.agent_confidence < LOW_CONFIDENCE:
        return True
    if req.decision_type == DecisionType.pickup_logistics and g.pickup_time:
        return True  # confirm the concrete handover with the human
    return False


def _target_person(req: DecisionRequest) -> TargetPerson:
    if req.decision_type == DecisionType.safety_flag:
        return TargetPerson.manager
    if req.decision_type in (DecisionType.price_over_budget, DecisionType.approve_purchase):
        # spend-authority routing: smallest role that can sign off the amount
        return config.person_for_budget(req.org_id, _amount(req))
    return config.decision_owner(req.org_id, req.decision_type)


def _urgency(req: DecisionRequest, g: Guardrail) -> UrgencyTier:
    urgent_prior = g.urgency_prior in (UrgencyTier.urgent_push, UrgencyTier.voice)
    far_over = _over_budget(req) and req.proposed_value > req.budget_cap * VOICE_OVERAGE_RATIO
    ambiguous = req.decision_type in (DecisionType.ambiguous_listing, DecisionType.safety_flag)
    if req.decision_type == DecisionType.safety_flag or far_over or (ambiguous and urgent_prior):
        return UrgencyTier.voice
    if urgent_prior or _over_budget(req) or req.agent_confidence < VERY_LOW_CONFIDENCE:
        return UrgencyTier.urgent_push
    return UrgencyTier.async_


def _message(req: DecisionRequest, person: TargetPerson, g: Guardrail) -> str:
    title = req.item.title if req.item else "an item"
    dt = req.decision_type
    if dt == DecisionType.price_over_budget:
        if req.proposed_value and req.budget_cap:
            over = req.proposed_value - req.budget_cap
            return (
                f"💸 {title}: seller wants €{req.proposed_value:.0f} "
                f"(€{over:.0f} over your €{req.budget_cap:.0f} cap). Approve, counter, or decline?"
            )
        return f"💸 {title}: price is above budget. Approve, counter, or decline?"
    if dt == DecisionType.approve_purchase:
        price = _amount(req)
        return f"🛒 Ready to buy {title} for €{price:.0f}. Confirm purchase?"
    if dt == DecisionType.pickup_logistics:
        when = g.pickup_time or "a proposed time"
        where = g.pickup_location or "the agreed place"
        return f"📍 Pickup for {title}: {when} at {where}. Confirm or adjust?"
    if dt == DecisionType.ambiguous_listing:
        return f"❓ Several listings match {title} — I need you to pick the right one."
    if dt == DecisionType.safety_flag:
        return f"⚠️ Safety check on {title}: {req.situation_text[:140]}"
    return req.situation_text[:160]


def _rationale(req: DecisionRequest, person: TargetPerson, urgency: UrgencyTier, g: Guardrail) -> str:
    bits = []
    if g.needs_signoff:
        bits.append("binding commitment detected → guardrail forces sign-off")
    if _over_budget(req):
        bits.append(f"€{req.proposed_value:.0f} over €{req.budget_cap:.0f} cap → {person.value}")
    if req.agent_confidence < LOW_CONFIDENCE:
        bits.append(f"low agent confidence ({req.agent_confidence:.2f})")
    if urgency == UrgencyTier.voice:
        bits.append("ambiguous + time-pressured → voice")
    return "; ".join(bits) or f"{req.decision_type.value} → {person.value}/{urgency.value}"


class RulesRouter:
    version = "rules-v0"

    def route(self, req: DecisionRequest, guardrail: Guardrail) -> RoutingDecision:
        should = _should_delegate(req, guardrail)
        person = _target_person(req) if should else TargetPerson.none
        urgency = _urgency(req, guardrail)
        return RoutingDecision(
            request_id=req.request_id,
            should_delegate=should,
            target_person=person,
            urgency_tier=urgency,
            suggested_message=_message(req, person, guardrail),
            rationale=_rationale(req, person, urgency, guardrail),
            model_version=self.version,
            guardrail=guardrail,
        )


def get_router():
    """Return the active router. When a Pioneer model id is configured we'll
    return PioneerRouter (falling back to rules on any error); for now, rules."""
    import os

    if os.getenv("PIONEER_API_KEY") and os.getenv("PIONEER_ROUTER_MODEL"):
        try:
            from pioneer.router_client import PioneerRouter  # type: ignore

            return PioneerRouter(fallback=RulesRouter())
        except Exception:
            pass
    return RulesRouter()
