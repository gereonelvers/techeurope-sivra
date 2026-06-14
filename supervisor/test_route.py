"""Tests for the stateless, policy-driven `POST /route` endpoint.

Run with pytest, or standalone:  .venv/bin/python -m supervisor.test_route

These cover the four contract cases from ARCHITECTURE.md:
  * in-budget, high-confidence approve   -> no/low delegation + buyer/async
  * over-budget                          -> procurement/manager + urgent_push
  * far-over-budget (> voiceOverageRatio)
    OR safety_flag                       -> manager + voice
  * needs_signoff situation_text         -> forced delegate + manager + voice
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from supervisor.app import app  # noqa: E402

client = TestClient(app)


# A representative org policy in the new PolicyPayload shape (cents).
POLICY = {
    "rules": [
        {"maxBudgetCents": 15_000, "targetPurchasingRole": "buyer",
         "urgency": "async", "autoApprove": True, "minConfidence": 0.6},
        {"maxBudgetCents": 50_000, "targetPurchasingRole": "procurement_lead",
         "urgency": "urgent_push", "autoApprove": False, "minConfidence": 0.6},
        {"maxBudgetCents": None, "targetPurchasingRole": "manager",
         "urgency": "urgent_push", "autoApprove": False, "minConfidence": 0.6},
    ],
    "autoApproveMaxCents": 5_000,   # €50
    "voiceOverageRatio": 1.5,
    "members": [
        {"purchasingRole": "buyer", "approvalLimitCents": 15_000, "membershipId": "mem-buyer"},
        {"purchasingRole": "procurement_lead", "approvalLimitCents": 50_000, "membershipId": "mem-proc"},
        {"purchasingRole": "manager", "approvalLimitCents": 500_000, "membershipId": "mem-mgr"},
    ],
}


def _route(request: dict, policy: dict | None = POLICY) -> dict:
    body: dict = {"request": request}
    if policy is not None:
        body["policy"] = policy
    resp = client.post("/route", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 1. in-budget, high-confidence approve -> no/low delegation, buyer/async ────
def test_in_budget_high_confidence_approve_auto_handles():
    out = _route({
        "decision_type": "approve_purchase",
        "situation_text": "Ready to buy a cable for €30. Routine, in budget.",
        "proposed_value": 30.0,
        "budget_cap": 150.0,
        "agent_confidence": 0.95,
        "item": {"title": "USB-C cable", "listed_price": 30.0},
    })
    assert out["should_delegate"] is False
    assert out["target_purchasing_role"] == "none"
    assert out["urgency_tier"] == "async"


def test_in_budget_buyer_band_low_urgency():
    # in-budget but a confirmation that does delegate (ambiguous) stays buyer/async-ish
    out = _route({
        "decision_type": "approve_purchase",
        "situation_text": "Buy the charger for €90, in budget, but please confirm.",
        "proposed_value": 90.0,
        "budget_cap": 150.0,
        "agent_confidence": 0.5,  # below band minConfidence -> delegates
        "item": {"title": "Charger", "listed_price": 90.0},
    })
    assert out["should_delegate"] is True
    assert out["target_purchasing_role"] == "buyer"
    assert out["target_membership_id"] == "mem-buyer"
    assert out["urgency_tier"] == "async"


# ── 2. over-budget -> procurement/manager + urgent_push ────────────────────────
def test_over_budget_procurement_urgent_push():
    out = _route({
        "decision_type": "price_over_budget",
        "situation_text": "Seller wants €420 for the bike, your cap is €400.",
        "proposed_value": 420.0,
        "budget_cap": 400.0,
        "agent_confidence": 0.8,
        "item": {"title": "Specialized Allez", "listed_price": 420.0},
    })
    assert out["should_delegate"] is True
    assert out["target_purchasing_role"] in ("procurement_lead", "manager")
    assert out["urgency_tier"] == "urgent_push"
    assert out["target_membership_id"] in ("mem-proc", "mem-mgr")


# ── 3a. far-over-budget (> voiceOverageRatio) -> voice ─────────────────────────
def test_far_over_budget_goes_voice():
    out = _route({
        "decision_type": "price_over_budget",
        "situation_text": "Seller now wants €700 vs your €400 cap.",
        "proposed_value": 700.0,   # 1.75x cap > 1.5 ratio
        "budget_cap": 400.0,
        "agent_confidence": 0.8,
        "item": {"title": "Specialized Allez", "listed_price": 700.0},
    })
    assert out["should_delegate"] is True
    assert out["urgency_tier"] == "voice"


# ── 3b. safety_flag -> manager + voice ─────────────────────────────────────────
def test_safety_flag_manager_voice():
    out = _route({
        "decision_type": "safety_flag",
        "situation_text": "Seller wants payment in gift cards before shipping.",
        "proposed_value": 200.0,
        "budget_cap": 400.0,
        "agent_confidence": 0.7,
        "item": {"title": "iPhone 12", "listed_price": 200.0},
    })
    assert out["should_delegate"] is True
    assert out["target_purchasing_role"] == "manager"
    assert out["target_membership_id"] == "mem-mgr"
    assert out["urgency_tier"] == "voice"


# ── 4. needs_signoff situation_text -> forced delegate + manager + voice ───────
def test_needs_signoff_forces_manager_voice():
    # a binding-commitment phrase trips the guardrail's needs_signoff override.
    out = _route({
        "decision_type": "approve_purchase",
        "situation_text": "I told the seller it's a deal and I'll take it for €30.",
        "proposed_value": 30.0,     # trivially in budget...
        "budget_cap": 150.0,
        "agent_confidence": 0.99,   # ...and high confidence, yet still forced
        "item": {"title": "USB-C cable", "listed_price": 30.0},
    })
    assert out["should_delegate"] is True
    assert out["target_purchasing_role"] == "manager"
    assert out["target_membership_id"] == "mem-mgr"
    assert out["urgency_tier"] == "voice"
    assert out["guardrail"]["needs_signoff"] is True


# ── default policy (policy omitted) still routes (mirrors rules-v0) ────────────
def test_default_policy_when_omitted():
    out = _route(
        {
            "decision_type": "price_over_budget",
            "situation_text": "Seller wants €420, cap €400.",
            "proposed_value": 420.0,
            "budget_cap": 400.0,
            "agent_confidence": 0.8,
            "item": {"title": "Bike", "listed_price": 420.0},
        },
        policy=None,
    )
    assert out["should_delegate"] is True
    assert out["urgency_tier"] == "urgent_push"
    # default policy still resolves a membership id (the synthetic defaults)
    assert out["target_membership_id"] is not None
    # back-compat: legacy target_person stays populated
    assert out["target_person"] in ("procurement_lead", "manager")


# ── back-compat: legacy target_person populated alongside the new fields ───────
def test_backcompat_target_person_populated():
    out = _route({
        "decision_type": "safety_flag",
        "situation_text": "Scam vibes, asks for a deposit off-platform.",
        "proposed_value": 200.0,
        "budget_cap": 400.0,
        "agent_confidence": 0.7,
        "item": {"title": "Camera", "listed_price": 200.0},
    })
    assert out["target_person"] == "manager"          # legacy enum field
    assert out["target_purchasing_role"] == "manager"  # new policy field


_TESTS = [
    test_in_budget_high_confidence_approve_auto_handles,
    test_in_budget_buyer_band_low_urgency,
    test_over_budget_procurement_urgent_push,
    test_far_over_budget_goes_voice,
    test_safety_flag_manager_voice,
    test_needs_signoff_forces_manager_voice,
    test_default_policy_when_omitted,
    test_backcompat_target_person_populated,
]


def _main() -> int:
    passed, failed = 0, 0
    for t in _TESTS:
        try:
            t()
            passed += 1
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # pragma: no cover
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
