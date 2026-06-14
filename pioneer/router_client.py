"""Route via the fine-tuned Pioneer model instead of the rules engine.

Drops in behind supervisor.router.get_router() when PIONEER_ROUTER_MODEL is set.
Uses the *exact* training prompt (pioneer.dataset._SYS + render_user) so the model
sees inputs identical to its SFT data. Falls back to the rules router on any error,
and always honours the GLiNER2 guardrail's needs_signoff safety override.

Adaptive-inference feedback (Loop A, step 3): each inference returns an id; we
capture it (keyed by request_id) so a later human correction can be posted back via
PioneerClient.feedback() — the online half of the self-improvement loop. The post is
best-effort: a missing id or a 403 (billing) is a silent no-op, never a crash.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from openai import OpenAI

from pioneer.dataset import _SYS, render_user
from shared.contracts.schema import (
    DecisionRequest,
    Guardrail,
    RoutingDecision,
    TargetPerson,
    UrgencyTier,
)


def _extract_inference_id(resp) -> Optional[str]:
    """Pull the per-inference id off an OpenAI-compatible response, tolerating the
    several shapes Pioneer may use (top-level id, or a nested metadata field)."""
    for getter in (
        lambda r: getattr(r, "id", None),
        lambda r: getattr(r, "inference_id", None),
        lambda r: (r.model_dump() if hasattr(r, "model_dump") else {}).get("inference_id"),
        lambda r: (r.model_dump() if hasattr(r, "model_dump") else {}).get("id"),
    ):
        try:
            v = getter(resp)
            if v:
                return str(v)
        except Exception:
            continue
    return None


class PioneerRouter:
    def __init__(self, fallback, model: Optional[str] = None) -> None:
        self.fallback = fallback
        # Per-request model override (a Pioneer training-job id) wins over the
        # PIONEER_ROUTER_MODEL env default, so the app's DB-backed active model
        # can drive routing without redeploying the supervisor.
        self.model = model or os.environ["PIONEER_ROUTER_MODEL"]
        self.version = f"pioneer:{self.model[:8]}"
        self.client = OpenAI(
            api_key=os.environ["PIONEER_API_KEY"],
            base_url=os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai/v1"),
        )
        # request_id -> inference_id, so a later human correction can be attributed
        # to the exact inference that produced the routing.
        self._inference_ids: dict[str, str] = {}
        self._pioneer_client = None  # lazy PioneerClient for feedback posts

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
            # Pioneer returns an inference id on the response; capture it for the
            # adaptive-inference feedback loop when available.
            inf_id = _extract_inference_id(resp)
            if inf_id:
                self._inference_ids[req.request_id] = inf_id
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
            )
        except Exception:
            return self.fallback.route(req, guardrail)

    def inference_id_for(self, request_id: str) -> Optional[str]:
        """The inference id captured for a prior route() call, if any."""
        return self._inference_ids.get(request_id)

    def feedback(
        self,
        inference_id: Optional[str],
        verdict: str,
        corrected_output: Optional[dict] = None,
    ) -> Optional[dict]:
        """Post a human correction back to Pioneer adaptive inference so the model
        can self-improve online (the live counterpart to the batch retrain loop).

        Best-effort by design: if no inference id was captured (e.g. the API didn't
        return one yet, or billing isn't on) this is a no-op returning None. Network
        / 403 errors are swallowed so a correction never breaks the request path.

        `verdict`           : "good" | "partial" | "wrong" (HumanRating value).
        `corrected_output`  : the label the model should have produced, shaped like
                              supervisor.reward.corrected_output()
                              ({should_delegate, target_person, urgency_tier}).
        """
        if not inference_id:
            return None
        try:
            if self._pioneer_client is None:
                from pioneer.client import PioneerClient  # lazy import
                self._pioneer_client = PioneerClient()
            return self._pioneer_client.feedback(inference_id, verdict, corrected_output)
        except Exception:
            # absent id / 403 / transport error -> silent no-op
            return None
