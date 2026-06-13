"""Reward computation + JSONL logging for the delegation self-improvement loop
(beat #3). Each resolved delegation becomes one training/feedback record:
(context → predicted routing → human rating → reward)."""
from __future__ import annotations

import json
from pathlib import Path

from shared.contracts.schema import HumanRating, HumanResolution, RoutingDecision, DecisionRequest

REWARD_LOG = Path(__file__).resolve().parent.parent / "data" / "router_rewards.jsonl"

_BASE = {HumanRating.good: 1.0, HumanRating.partial: 0.0, HumanRating.wrong: -1.0}
LATENCY_TIER_MS = {"async": 600_000, "urgent_push": 120_000, "voice": 60_000}


def compute_reward(decision: RoutingDecision, resolution: HumanResolution) -> float:
    r = _BASE.get(resolution.rating, 0.0) if resolution.rating else 0.0
    if resolution.corrected_person and resolution.corrected_person != decision.target_person:
        r -= 0.3
    if resolution.corrected_urgency and resolution.corrected_urgency != decision.urgency_tier:
        r -= 0.3
    # latency vs predicted urgency: a slow response to a "voice"/"urgent" ping
    # suggests we over-escalated; very fast on "async" suggests under-escalated.
    budget = LATENCY_TIER_MS.get(decision.urgency_tier.value)
    if budget and resolution.latency_ms > budget:
        r -= 0.2
    return round(max(-2.0, min(1.0, r)), 3)


def corrected_output(decision: RoutingDecision, resolution: HumanResolution) -> dict:
    """The label Pioneer adaptive-inference should learn from."""
    return {
        "should_delegate": decision.should_delegate,
        "target_person": (resolution.corrected_person or decision.target_person).value,
        "urgency_tier": (resolution.corrected_urgency or decision.urgency_tier).value,
    }


def log_reward(req: DecisionRequest, decision: RoutingDecision, resolution: HumanResolution) -> dict:
    reward = compute_reward(decision, resolution)
    record = {
        "request_id": decision.request_id,
        "model_version": decision.model_version,
        "context": req.model_dump(mode="json"),
        "guardrail": decision.guardrail.model_dump(mode="json") if decision.guardrail else None,
        "predicted": {
            "should_delegate": decision.should_delegate,
            "target_person": decision.target_person.value,
            "urgency_tier": decision.urgency_tier.value,
        },
        "corrected": corrected_output(decision, resolution),
        "human": resolution.model_dump(mode="json"),
        "reward": reward,
    }
    REWARD_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(REWARD_LOG, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return record
