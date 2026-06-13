"""A spread of buyer-agent escalations that exercise every (person × urgency)
cell. Used by the demo and the verification script."""
from __future__ import annotations

from shared.contracts.schema import DecisionRequest, DecisionType, Item

SCENARIOS: list[DecisionRequest] = [
    # in-budget routine purchase a buyer can sign off → buyer / async
    DecisionRequest(
        agent_id="buyer-003",
        marketplace="site-a",
        decision_type=DecisionType.approve_purchase,
        situation_text="Found an exact match: 'Specialized Allez 56cm' for 120€, condition Good, seller rating 4.9. Ready to buy.",
        item=Item(title="Specialized Allez 56cm road bike", listed_price=120.0, item_id=412),
        proposed_value=120.0,
        budget_cap=400.0,
        agent_confidence=0.95,
    ),
    # over budget, mid value → procurement_lead / urgent_push
    DecisionRequest(
        agent_id="buyer-007",
        marketplace="site-c",
        decision_type=DecisionType.price_over_budget,
        situation_text="Seller counter-offered 340€ for the ThinkPad X1 (listed 300€). He'll only meet Saturday 8pm in Wedding. My cap is 320€.",
        item=Item(title="ThinkPad X1 Carbon", listed_price=300.0, item_id=91),
        proposed_value=340.0,
        budget_cap=320.0,
        agent_confidence=0.55,
    ),
    # ambiguous + time pressure → buyer / voice
    DecisionRequest(
        agent_id="buyer-011",
        marketplace="site-b",
        decision_type=DecisionType.ambiguous_listing,
        situation_text="Two listings match 'iPhone 12 128GB' — one 280€ 'like new', one 250€ but the condition photos are unclear. The cheaper listing ends in an hour.",
        item=Item(title="iPhone 12 128GB", item_id=None),
        agent_confidence=0.38,
    ),
    # pickup confirmation, in budget → buyer / async
    DecisionRequest(
        agent_id="buyer-003",
        marketplace="site-a",
        decision_type=DecisionType.pickup_logistics,
        situation_text="Seller confirmed the bike. Proposes handover Saturday 3pm at Marienplatz. Need your ok on time and place.",
        item=Item(title="Specialized Allez 56cm road bike", listed_price=120.0, item_id=412),
        agent_confidence=0.8,
    ),
    # safety / off-platform → manager / voice
    DecisionRequest(
        agent_id="buyer-022",
        marketplace="site-c",
        decision_type=DecisionType.safety_flag,
        situation_text="Seller is pushing to pay via gift cards and ship before payment clears, off-platform. Says it's a deal if I send now.",
        item=Item(title="Sony A7 III camera", listed_price=900.0, item_id=7),
        proposed_value=900.0,
        budget_cap=1000.0,
        agent_confidence=0.2,
    ),
    # high value over budget → manager / voice (far over)
    DecisionRequest(
        agent_id="buyer-031",
        marketplace="site-c",
        decision_type=DecisionType.price_over_budget,
        situation_text="Best MacBook Pro 16 I can find is 1500€, but your cap was 900€. It's genuinely the cheapest in the city.",
        item=Item(title="MacBook Pro 16 M1", listed_price=1500.0, item_id=55),
        proposed_value=1500.0,
        budget_cap=900.0,
        agent_confidence=0.6,
    ),
]
