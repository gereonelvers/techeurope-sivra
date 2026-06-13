"""Shared resolution logic used by both the JSON API (/resolve) and the web reply
page (/d/{code}). Records the human's answer, computes latency, logs the reward,
and fires the agent callback."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from shared.contracts.schema import HumanResolution
from supervisor import reward
from supervisor.store import STORE


def resolve_request(resolution: HumanResolution) -> HumanResolution:
    req = STORE.requests.get(resolution.request_id)
    decision = STORE.decisions.get(resolution.request_id)
    if not req or not decision:
        raise KeyError(resolution.request_id)
    if not resolution.latency_ms:
        delta = datetime.now(timezone.utc) - decision.decided_at
        resolution.latency_ms = max(0, int(delta.total_seconds() * 1000))
    STORE.resolve(resolution)
    reward.log_reward(req, decision, resolution)
    if req.callback_url:
        try:
            httpx.post(req.callback_url, json=resolution.model_dump(mode="json"), timeout=5)
        except Exception:
            pass
    return resolution
