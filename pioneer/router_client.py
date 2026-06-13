"""Route via the fine-tuned Pioneer model instead of the rules engine.

Drops in behind supervisor.router.get_router() when PIONEER_ROUTER_MODEL is set.
Uses the *exact* training prompt (pioneer.dataset._SYS + render_user) so the model
sees inputs identical to its SFT data. Falls back to the rules router on any error,
and always honours the GLiNER2 guardrail's needs_signoff safety override.
"""
from __future__ import annotations

import json
import os

from openai import OpenAI

from pioneer.dataset import _SYS, render_user
from shared.contracts.schema import (
    DecisionRequest,
    Guardrail,
    RoutingDecision,
    TargetPerson,
    UrgencyTier,
)


class PioneerRouter:
    def __init__(self, fallback) -> None:
        self.fallback = fallback
        self.model = os.environ["PIONEER_ROUTER_MODEL"]
        self.version = f"pioneer:{self.model[:8]}"
        self.client = OpenAI(
            api_key=os.environ["PIONEER_API_KEY"],
            base_url=os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai/v1"),
        )

    def route(self, req: DecisionRequest, guardrail: Guardrail) -> RoutingDecision:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYS},
                    {"role": "user", "content": render_user(req, guardrail)},
                ],
                temperature=0,
                max_tokens=300,
            )
            d = json.loads(resp.choices[0].message.content)
            should = bool(d["should_delegate"]) or guardrail.needs_signoff  # safety override
            return RoutingDecision(
                request_id=req.request_id,
                should_delegate=should,
                target_person=TargetPerson(d["target_person"]),
                urgency_tier=UrgencyTier(d["urgency_tier"]),
                suggested_message=d.get("suggested_message", "") or req.situation_text[:160],
                rationale="routed by the fine-tuned delegation model",
                model_version=self.version,
                guardrail=guardrail,
                # Pioneer returns an inference id on the response; capture it for the
                # adaptive-inference feedback loop when available.
            )
        except Exception:
            return self.fallback.route(req, guardrail)
