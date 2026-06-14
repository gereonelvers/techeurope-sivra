"""Stateless, policy-driven routing brain — `POST /route`.

This is the new contract from ARCHITECTURE.md ("Supervisor (stateless) contract"):
the supervisor becomes a *pure function* over a `DecisionRequest` + an org's
permission `policy`, returning a `RoutingDecision`. No DB, no STORE, no dispatch —
the Next.js app owns persistence/audit/notification and calls this.

What stays from the legacy `/escalate` path:
  * the GLiNER2 guardrail (`extract_guardrail`) over `situation_text`,
  * the `needs_signoff` HARD override (force delegate + manager + voice),
  * the Pioneer fine-tuned router as an optional brain (PIONEER_ROUTER_MODEL):
    when present it proposes should_delegate/urgency, which the policy then maps
    onto a concrete purchasing role + membership.

What's new: routing target + urgency + auto-approve come FROM the policy
(budget bands → role/urgency/autoApprove; autoApproveMaxCents; voiceOverageRatio;
per-rule minConfidence) instead of the hardcoded `router.py` constants / org.yaml.
If `policy` is omitted we synthesise a default that mirrors today's rules-v0.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from shared.contracts.schema import (
    DecisionRequest,
    DecisionType,
    Guardrail,
    RoutingDecision,
    TargetPerson,
    UrgencyTier,
)
from supervisor.guardrail import extract_guardrail
from supervisor.router import RulesRouter, get_router

router = APIRouter()


# ── Policy payload (mirrors the app's PermissionPolicy shape) ──────────────────
class PolicyRule(BaseModel):
    """One budget band. Bands are matched by ceiling: the narrowest band whose
    `maxBudgetCents` is >= the amount wins. `maxBudgetCents == None` = open-ended
    (catch-all top band)."""

    maxBudgetCents: Optional[int] = None
    targetPurchasingRole: str
    urgency: str = "async"  # "async" | "urgent_push" | "voice"
    autoApprove: bool = False
    minConfidence: Optional[float] = None


class PolicyMember(BaseModel):
    purchasingRole: str
    approvalLimitCents: Optional[int] = None
    membershipId: str


class PolicyPayload(BaseModel):
    rules: List[PolicyRule] = Field(default_factory=list)
    autoApproveMaxCents: int = 0
    voiceOverageRatio: float = 1.5
    members: List[PolicyMember] = Field(default_factory=list)


class RouteRequest(BaseModel):
    request: DecisionRequest
    policy: Optional[PolicyPayload] = None
    # Optional Pioneer training-job id to route THIS request with. When present,
    # the supervisor binds a PioneerRouter to exactly this model (the app's
    # DB-backed active model) instead of the PIONEER_ROUTER_MODEL env default.
    # On any error constructing/calling it, we fall back to the rules/policy path.
    model: Optional[str] = None


# ── Default policy (mirrors rules-v0 / org.yaml so policy-less callers work) ────
# org.yaml budgets were euros: buyer 150, procurement_lead 500, manager 5000.
# router.py constants: AUTO_APPROVE_MAX=50, VOICE_OVERAGE_RATIO=1.5, LOW_CONF=0.6.
_DEFAULT_RULES_V0 = PolicyPayload(
    rules=[
        PolicyRule(maxBudgetCents=15_000, targetPurchasingRole="buyer",
                   urgency="async", autoApprove=True, minConfidence=0.6),
        PolicyRule(maxBudgetCents=50_000, targetPurchasingRole="procurement_lead",
                   urgency="urgent_push", autoApprove=False, minConfidence=0.6),
        PolicyRule(maxBudgetCents=None, targetPurchasingRole="manager",
                   urgency="urgent_push", autoApprove=False, minConfidence=0.6),
    ],
    autoApproveMaxCents=5_000,  # €50
    voiceOverageRatio=1.5,
    members=[
        PolicyMember(purchasingRole="buyer", approvalLimitCents=15_000, membershipId="default-buyer"),
        PolicyMember(purchasingRole="procurement_lead", approvalLimitCents=50_000, membershipId="default-procurement"),
        PolicyMember(purchasingRole="manager", approvalLimitCents=500_000, membershipId="default-manager"),
    ],
)

# legacy enum target_person is kept populated for back-compat; map our well-known
# purchasing-role names onto it where we recognise them, else fall back sensibly.
_ROLE_TO_LEGACY = {
    "buyer": TargetPerson.buyer,
    "procurement_lead": TargetPerson.procurement_lead,
    "procurement": TargetPerson.procurement_lead,
    "manager": TargetPerson.manager,
    "none": TargetPerson.none,
}


def _amount_cents(req: DecisionRequest) -> int:
    """Best-effort amount in integer cents (schema carries euros as floats)."""
    val = None
    if req.proposed_value:
        val = float(req.proposed_value)
    elif req.item and req.item.listed_price:
        val = float(req.item.listed_price)
    if val is None:
        return 0
    return int(round(val * 100))


def _over_budget(req: DecisionRequest) -> bool:
    return bool(req.proposed_value and req.budget_cap and req.proposed_value > req.budget_cap)


def _far_over_budget(req: DecisionRequest, ratio: float) -> bool:
    return bool(
        req.proposed_value
        and req.budget_cap
        and req.proposed_value > req.budget_cap * ratio
    )


def _is_urgent_prior(g: Guardrail) -> bool:
    return g.urgency_prior in (UrgencyTier.urgent_push, UrgencyTier.voice)


def _select_band(policy: PolicyPayload, amount_cents: int) -> Optional[PolicyRule]:
    """Narrowest band whose ceiling covers `amount_cents`. Open-ended bands
    (maxBudgetCents is None) are catch-alls of last resort."""
    capped = sorted(
        (r for r in policy.rules if r.maxBudgetCents is not None),
        key=lambda r: r.maxBudgetCents,
    )
    for rule in capped:
        if amount_cents <= rule.maxBudgetCents:
            return rule
    open_ended = [r for r in policy.rules if r.maxBudgetCents is None]
    if open_ended:
        return open_ended[0]
    return capped[-1] if capped else None


def _legacy_person(role: str) -> TargetPerson:
    return _ROLE_TO_LEGACY.get(role, TargetPerson.manager)


def _resolve_membership(policy: PolicyPayload, role: str) -> Optional[str]:
    for m in policy.members:
        if m.purchasingRole == role:
            return m.membershipId
    return None


def _urgency_str_to_tier(u: str) -> UrgencyTier:
    try:
        return UrgencyTier(u)
    except ValueError:
        return UrgencyTier.async_


def _max_tier(a: UrgencyTier, b: UrgencyTier) -> UrgencyTier:
    order = {UrgencyTier.async_: 0, UrgencyTier.urgent_push: 1, UrgencyTier.voice: 2}
    return a if order[a] >= order[b] else b


_ALWAYS_DELEGATE = {
    DecisionType.safety_flag,
    DecisionType.approve_purchase,
    DecisionType.ambiguous_listing,
}


def _message(req: DecisionRequest, g: Guardrail) -> str:
    """Reuse the legacy message phrasing — it's product copy, role-agnostic."""
    from supervisor.router import _message as _legacy_message  # local import: shared copy

    # legacy _message takes a TargetPerson but only uses it for branchless text;
    # pass a placeholder — the copy doesn't depend on the resolved role.
    return _legacy_message(req, TargetPerson.none, g)


def _active_router(model: Optional[str]):
    """Select the routing brain. With an explicit `model` (a Pioneer job-id) we
    bind a PioneerRouter to exactly that model; otherwise we use the process
    default via get_router(). Any failure (missing key, import error) degrades to
    the always-available RulesRouter so /route never hard-fails on the model path."""
    if model:
        try:
            from pioneer.router_client import PioneerRouter  # type: ignore

            return PioneerRouter(fallback=RulesRouter(), model=model)
        except Exception:
            return RulesRouter()
    return get_router()


def route_decision(
    req: DecisionRequest,
    policy: Optional[PolicyPayload],
    model: Optional[str] = None,
) -> RoutingDecision:
    """Pure function: (DecisionRequest, policy[, model]) -> RoutingDecision.

    No side effects. `model` (a Pioneer training-job id) optionally overrides the
    routing brain for this call; on any error it falls back to the policy/rules
    path so existing callers and the live supervisor are never broken."""
    policy = policy or _DEFAULT_RULES_V0
    guardrail = extract_guardrail(req)
    amount_cents = _amount_cents(req)
    over = _over_budget(req)
    urgent_prior = _is_urgent_prior(guardrail)

    # ── 1. needs_signoff HARD override (safety): delegate + manager + voice ────
    if guardrail.needs_signoff:
        role = "manager"
        person = _legacy_person(role)
        return RoutingDecision(
            request_id=req.request_id,
            should_delegate=True,
            target_person=person,
            target_purchasing_role=role,
            target_membership_id=_resolve_membership(policy, role),
            urgency_tier=UrgencyTier.voice,
            suggested_message=_message(req, guardrail),
            rationale="binding commitment detected -> guardrail forces sign-off (manager/voice)",
            model_version="policy-v1",
            guardrail=guardrail,
        )

    # ── 2. pick the budget band from the policy ───────────────────────────────
    band = _select_band(policy, amount_cents)
    band_role = band.targetPurchasingRole if band else "manager"
    band_urgency = _urgency_str_to_tier(band.urgency) if band else UrgencyTier.urgent_push
    band_auto = bool(band.autoApprove) if band else False
    band_min_conf = band.minConfidence if (band and band.minConfidence is not None) else 0.6

    # ── 3. optional Pioneer brain proposes delegate/urgency; policy maps it ────
    model_version = "policy-v1"
    pioneer_should: Optional[bool] = None
    pioneer_urgency: Optional[UrgencyTier] = None
    active = _active_router(model)
    if not isinstance(active, RulesRouter):
        try:
            proposal = active.route(req, guardrail)
            pioneer_should = proposal.should_delegate
            pioneer_urgency = proposal.urgency_tier
            model_version = f"policy-v1+{proposal.model_version}"
        except Exception:
            pioneer_should = None
            pioneer_urgency = None

    # ── 4. should_delegate: policy auto-approve bands + global cap, else rules ─
    should = True
    rationale_bits: List[str] = []

    auto_eligible = (
        req.decision_type == DecisionType.approve_purchase
        and band_auto
        and amount_cents <= policy.autoApproveMaxCents
        and req.agent_confidence >= 0.9
        and not over
        and not urgent_prior
    )
    if auto_eligible:
        should = False
        rationale_bits.append(
            f"in-budget, high-confidence routine buy <= autoApproveMaxCents "
            f"(€{policy.autoApproveMaxCents / 100:.0f}) -> agent auto-handles"
        )
    elif req.decision_type in _ALWAYS_DELEGATE:
        should = True
        rationale_bits.append(f"{req.decision_type.value} always needs a human")
    elif over:
        should = True
        rationale_bits.append("proposed value over budget cap")
    elif req.agent_confidence < band_min_conf:
        should = True
        rationale_bits.append(
            f"agent confidence {req.agent_confidence:.2f} < band minConfidence {band_min_conf:.2f}"
        )
    elif req.decision_type == DecisionType.pickup_logistics and guardrail.pickup_time:
        should = True
        rationale_bits.append("concrete pickup handover needs confirmation")
    else:
        should = False
        rationale_bits.append("within policy bounds -> no human needed")

    # Pioneer may upgrade a non-delegation to a delegation (never downgrade a
    # safety/over-budget delegation away). It's an additional escalation signal.
    if pioneer_should is True and not should:
        should = True
        rationale_bits.append("Pioneer router escalated this case")

    # ── 5. resolve role / urgency from the policy band ────────────────────────
    if not should:
        role = "none"
        person = TargetPerson.none
        membership = None
        urgency = UrgencyTier.async_
    else:
        role = band_role
        person = _legacy_person(role)
        membership = _resolve_membership(policy, role)

        # base urgency = band urgency, escalated by signals
        urgency = band_urgency
        if urgent_prior:
            urgency = _max_tier(urgency, UrgencyTier.urgent_push)
        if over:
            urgency = _max_tier(urgency, UrgencyTier.urgent_push)
        if req.decision_type == DecisionType.safety_flag:
            role = "manager"
            person = _legacy_person(role)
            membership = _resolve_membership(policy, role)
            urgency = UrgencyTier.voice
            rationale_bits.append("safety flag -> manager/voice")
        # far-over-budget (> voiceOverageRatio) escalates to voice
        if _far_over_budget(req, policy.voiceOverageRatio):
            urgency = UrgencyTier.voice
            rationale_bits.append(
                f"> {policy.voiceOverageRatio:g}x budget cap -> voice"
            )
        # Pioneer urgency can raise (never lower) the tier
        if pioneer_urgency is not None:
            urgency = _max_tier(urgency, pioneer_urgency)

    return RoutingDecision(
        request_id=req.request_id,
        should_delegate=should,
        target_person=person,
        target_purchasing_role=role,
        target_membership_id=membership,
        urgency_tier=urgency,
        suggested_message=_message(req, guardrail),
        rationale="; ".join(rationale_bits),
        model_version=model_version,
        guardrail=guardrail,
    )


@router.post("/route", response_model=RoutingDecision)
def route(body: RouteRequest) -> RoutingDecision:
    """Stateless routing: (DecisionRequest + org policy) -> RoutingDecision.

    No persistence, no dispatch — the caller (apps/web) owns those. If `policy`
    is omitted, a default mirroring rules-v0 is used so policy-less callers work.
    `body.model` (optional Pioneer job-id) overrides the routing brain for this
    request — that's how the app's DB-backed active model drives live routing.
    """
    return route_decision(body.request, body.policy, body.model)
