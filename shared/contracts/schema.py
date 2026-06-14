"""Shared handoff contract between the buyer-agent fleet (subsystem 1) and the
delegation supervisor (subsystem 2).

This is the seam of the whole system. Keep it dependency-light (pydantic only)
so it can be imported from anywhere — the marketplace, the agents, the
supervisor, the eval harness.

Flow:
    buyer agent --DecisionRequest--> supervisor  (POST /escalate)
    supervisor  --RoutingDecision--> delivery    (Telegram / voice)
    human       --HumanResolution--> supervisor  (POST /resolve/{id})
    supervisor  --HumanResolution--> buyer agent (callback or GET /resolution/{id})
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


# ── Enums ─────────────────────────────────────────────────────────────────────
class DecisionType(str, Enum):
    price_over_budget = "price_over_budget"
    pickup_logistics = "pickup_logistics"
    ambiguous_listing = "ambiguous_listing"
    approve_purchase = "approve_purchase"
    safety_flag = "safety_flag"


class TargetPerson(str, Enum):
    none = "none"
    buyer = "buyer"
    procurement_lead = "procurement_lead"
    manager = "manager"


class UrgencyTier(str, Enum):
    # NB: "async" is a Python keyword, so the member is async_ with value "async".
    async_ = "async"
    urgent_push = "urgent_push"
    voice = "voice"


class Resolution(str, Enum):
    approve = "approve"
    counter = "counter"
    decline = "decline"
    escalate = "escalate"


class HumanRating(str, Enum):
    good = "good"        # right person & urgency
    partial = "partial"  # roughly right
    wrong = "wrong"      # wrong person and/or urgency


# ── Payloads ──────────────────────────────────────────────────────────────────
class Item(BaseModel):
    title: str
    listed_price: Optional[float] = None
    currency: str = "EUR"
    item_id: Optional[int] = None
    url: Optional[str] = None


class DecisionRequest(BaseModel):
    """Emitted by a buyer agent when it hits a step it should not auto-execute."""
    request_id: str = Field(default_factory=new_id)
    episode_id: Optional[str] = None
    agent_id: str = "buyer-000"
    org_id: str = "org-acme"
    marketplace: str = "site-a"
    decision_type: DecisionType
    situation_text: str
    item: Optional[Item] = None
    proposed_value: Optional[float] = None
    budget_cap: Optional[float] = None
    agent_confidence: float = 0.5
    screenshot_url: Optional[str] = None
    callback_url: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class Guardrail(BaseModel):
    """Structured fields from GLiNER2 (or the regex fallback) over situation_text.

    `needs_signoff` is a hard safety override: if true, the supervisor delegates
    regardless of what the router model decides.
    """
    needs_signoff: bool = False
    urgency_prior: Optional[UrgencyTier] = None
    counter_offer: Optional[float] = None
    pickup_time: Optional[str] = None
    pickup_location: Optional[str] = None
    condition: Optional[str] = None
    commitments: List[str] = Field(default_factory=list)
    extractor: str = "fallback"  # "gliner2" | "fallback"


class RoutingDecision(BaseModel):
    """The supervisor's routing decision: who to ping and how loudly."""
    request_id: str
    should_delegate: bool
    target_person: TargetPerson
    urgency_tier: UrgencyTier
    suggested_message: str
    rationale: str = ""
    model_version: str = "rules-v0"
    guardrail: Optional[Guardrail] = None
    # Policy-driven routing (additive, stateless /route). `target_person` stays
    # populated for back-compat; these carry the org's own purchasing-role taxonomy
    # and the concrete membership resolved from the policy's member roster.
    target_purchasing_role: Optional[str] = None
    target_membership_id: Optional[str] = None
    decided_at: datetime = Field(default_factory=_now)


class HumanResolution(BaseModel):
    """The human's reply + the reward signal we learn from."""
    request_id: str
    resolved_by: str = "unknown"
    resolution: Resolution
    value: Optional[float] = None
    notes: Optional[str] = None
    latency_ms: int = 0
    # reward signal (beat #3):
    rating: Optional[HumanRating] = None
    corrected_person: Optional[TargetPerson] = None
    corrected_urgency: Optional[UrgencyTier] = None
    resolved_at: datetime = Field(default_factory=_now)
