"""Synthetic dataset builder for the delegation router (Pioneer side-challenge).

Strategy (matches the plan): a generator produces diverse buyer-agent escalation
*scenarios*; a deterministic rules oracle (our guardrail + RulesRouter) assigns
*labels*, so the synthetic labels are self-consistent — never LLM-hallucinated.
We deliberately include boundary cases (amounts at budget thresholds, confidence
near the delegate cutoff) so the fine-tune learns the decision surface, not noise.

Outputs (data/datasets/):
  router_scenarios.jsonl  raw labeled scenarios (context + labels)
  router_sft.jsonl        chat-format SFT for a Pioneer decoder (Gemma)
  router_eval.jsonl       held-out chat-format eval (same schema)

Run:  python pioneer/dataset.py --train 1500 --eval 300
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.contracts.schema import DecisionRequest, DecisionType, Item  # noqa: E402
from supervisor import config  # noqa: E402
from supervisor.guardrail import extract_guardrail  # noqa: E402
from supervisor.router import RulesRouter  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "datasets"
ORG = "org-acme"

CATALOG = {
    "Bikes": (["Specialized Allez", "Cube Aim", "Trek Domane", "Canyon Endurace", "Giant Escape"], (80, 600)),
    "Laptops": (["ThinkPad X1 Carbon", "MacBook Air M1", "Dell XPS 13", "HP Spectre x360"], (150, 1300)),
    "Phones": (["iPhone 12 128GB", "iPhone 13 Pro", "Samsung Galaxy S22", "Pixel 7"], (100, 900)),
    "Cameras": (["Sony A7 III", "Canon EOS R", "Fujifilm X-T4", "Nikon Z6"], (200, 1600)),
    "Furniture": (["Eames lounge chair", "USM Haller shelf", "Vitra desk", "oak dining table"], (40, 500)),
    "Audio": (["Sennheiser HD650", "Sonos Move", "Marshall amp", "AirPods Pro"], (60, 700)),
}
CITIES = ["München", "Berlin", "Hamburg", "Köln", "Frankfurt"]
SITES = ["site-a", "site-b", "site-c"]
SINGULAR = {"Bikes": "bike", "Laptops": "laptop", "Phones": "phone",
            "Cameras": "camera", "Furniture": "furniture", "Audio": "audio gear"}

# decision_type sampling weights (chosen to give person/urgency variety)
DTYPE_WEIGHTS = {
    DecisionType.price_over_budget: 0.30,
    DecisionType.approve_purchase: 0.25,
    DecisionType.pickup_logistics: 0.20,
    DecisionType.ambiguous_listing: 0.15,
    DecisionType.safety_flag: 0.10,
}

URGENT_CUES = [
    "He'll only meet tonight.", "Listing ends in an hour.", "Other buyers are circling.",
    "Says it's first come first served.", "Offer only stands until 6pm today.",
]
CALM_CUES = ["No rush on their end.", "Flexible on timing.", "Happy to wait for your call.", ""]
COMMIT_CUES = ["I told them it's a deal.", "I said I'll take it.", "I already confirmed we'd meet."]
PICKUP_PLACES = ["Marienplatz", "Berlin Hbf", "near the Köln station", "at the Hamburg park"]
PICKUP_TIMES = ["Saturday 3pm", "tomorrow 11am", "Friday 6pm", "Sunday noon"]
SCAM_CUES = [
    "Seller wants payment in gift cards before shipping.",
    "They ask to move off-platform and pay by bank transfer up front.",
    "Wants me to send a deposit to 'hold' it, no escrow.",
]


def _price(rng: random.Random, lo: int, hi: int) -> float:
    return float(rng.randint(lo, hi))


def gen_scenario(rng: random.Random) -> DecisionRequest:
    dtype = rng.choices(list(DTYPE_WEIGHTS), weights=list(DTYPE_WEIGHTS.values()))[0]
    cat = rng.choice(list(CATALOG))
    models, (lo, hi) = CATALOG[cat]
    title = rng.choice(models)
    listed = _price(rng, lo, hi)
    city = rng.choice(CITIES)
    conf = round(rng.uniform(0.2, 0.98), 2)
    item = Item(title=f"{title} ({SINGULAR[cat]})", listed_price=listed, item_id=rng.randint(1, 999))
    proposed = None
    budget = None
    text = ""

    if dtype == DecisionType.price_over_budget:
        budget = round(listed * rng.uniform(0.7, 1.05), 0)            # often below list
        proposed = round(listed * rng.uniform(1.0, 1.7), 0)           # seller counter
        cue = rng.choice(URGENT_CUES + CALM_CUES)
        text = f"Seller counter-offered €{proposed:.0f} for the {item.title} (listed €{listed:.0f}). My cap is €{budget:.0f}. {cue}".strip()

    elif dtype == DecisionType.approve_purchase:
        if rng.random() < 0.45:  # trivial in-budget micro-buy -> agent auto-handles (negative class)
            listed = float(rng.randint(8, 48))
            item = Item(title=item.title, listed_price=listed, item_id=item.item_id)
            conf = round(rng.uniform(0.9, 0.98), 2)
            budget = round(listed * rng.uniform(2.0, 5.0), 0)
            proposed = listed
            text = f"Small in-budget buy: {item.title} for €{listed:.0f}, exact match, seller rating {rng.uniform(4.5,5.0):.1f}. Proceeding unless you object."
        else:
            budget = round(listed * rng.uniform(1.0, 3.0), 0)        # within budget
            proposed = listed
            cue = rng.choice(CALM_CUES + URGENT_CUES[:2])
            text = f"Found an exact match for the {item.title} at €{listed:.0f}, condition Good, seller rating {rng.uniform(4.2,5.0):.1f}. Ready to buy. {cue}".strip()

    elif dtype == DecisionType.pickup_logistics:
        budget = round(listed * 2, 0)
        when = rng.choice(PICKUP_TIMES)
        where = rng.choice(PICKUP_PLACES)
        commit = rng.choice(COMMIT_CUES + ["", ""])
        text = f"Seller confirmed the {item.title}. Proposes handover {when} {where}. Need your ok on time and place. {commit}".strip()

    elif dtype == DecisionType.ambiguous_listing:
        budget = round(listed * 1.5, 0)
        alt = round(listed * rng.uniform(0.8, 0.95), 0)
        cue = rng.choice(URGENT_CUES + CALM_CUES)
        text = f"Two listings match '{item.title}' — one €{listed:.0f} 'like new', one €{alt:.0f} with unclear condition photos. {cue}".strip()
        conf = round(rng.uniform(0.2, 0.55), 2)

    else:  # safety_flag
        budget = round(listed * rng.uniform(1.0, 1.3), 0)
        proposed = listed
        text = f"{rng.choice(SCAM_CUES)} It's for the {item.title} (€{listed:.0f}). {rng.choice(COMMIT_CUES + [''])}".strip()
        conf = round(rng.uniform(0.15, 0.5), 2)

    return DecisionRequest(
        agent_id=f"buyer-{rng.randint(1, 99):03d}",
        org_id=ORG,
        marketplace=rng.choice(SITES),
        decision_type=dtype,
        situation_text=text,
        item=item,
        proposed_value=proposed,
        budget_cap=budget,
        agent_confidence=conf,
    )


_SYS = (
    "You are the delegation router for a fleet of autonomous buyer agents. Given a buyer agent's "
    "situation, decide whether a human must be involved, which person, and how urgently.\n"
    "Org policy (spend authority): buyer ≤ €150, procurement_lead ≤ €500, manager ≤ €5000. "
    "Safety concerns always go to the manager.\n"
    "target_person ∈ {buyer, procurement_lead, manager, none}; "
    "urgency_tier ∈ {async, urgent_push, voice}.\n"
    "Output ONLY JSON: {\"should_delegate\": bool, \"target_person\": str, \"urgency_tier\": str, \"suggested_message\": str}."
)


def render_user(req: DecisionRequest, guardrail) -> str:
    g = guardrail
    fields = {
        "marketplace": req.marketplace,
        "decision_type": req.decision_type.value,
        "item": req.item.title if req.item else None,
        "listed_price": req.item.listed_price if req.item else None,
        "proposed_value": req.proposed_value,
        "budget_cap": req.budget_cap,
        "agent_confidence": req.agent_confidence,
        "extracted": {
            "needs_signoff": g.needs_signoff,
            "urgency_prior": g.urgency_prior.value if g.urgency_prior else None,
            "counter_offer": g.counter_offer,
            "pickup_time": g.pickup_time,
            "pickup_location": g.pickup_location,
            "commitments": g.commitments,
        },
    }
    return f"SITUATION: {req.situation_text}\nCONTEXT: {json.dumps(fields, ensure_ascii=False)}"


def label_and_format(req: DecisionRequest, router: RulesRouter):
    guardrail = extract_guardrail(req)
    decision = router.route(req, guardrail)
    target = {
        "should_delegate": decision.should_delegate,
        "target_person": decision.target_person.value,
        "urgency_tier": decision.urgency_tier.value,
        "suggested_message": decision.suggested_message,
    }
    scenario = {
        "context": req.model_dump(mode="json"),
        "guardrail": guardrail.model_dump(mode="json"),
        "labels": target,
    }
    sft = {
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": render_user(req, guardrail)},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ]
    }
    return scenario, sft, target


def build(n_train: int, n_eval: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    router = RulesRouter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scen_f = (OUT_DIR / "router_scenarios.jsonl").open("w")
    sft_f = (OUT_DIR / "router_sft.jsonl").open("w")
    eval_f = (OUT_DIR / "router_eval.jsonl").open("w")
    dist = {"person": {}, "urgency": {}, "delegate": {True: 0, False: 0}}

    total = n_train + n_eval
    for i in range(total):
        req = gen_scenario(rng)
        scenario, sft, target = label_and_format(req, router)
        if i < n_train:
            scen_f.write(json.dumps(scenario, ensure_ascii=False) + "\n")
            sft_f.write(json.dumps(sft, ensure_ascii=False) + "\n")
            dist["person"][target["target_person"]] = dist["person"].get(target["target_person"], 0) + 1
            dist["urgency"][target["urgency_tier"]] = dist["urgency"].get(target["urgency_tier"], 0) + 1
            dist["delegate"][target["should_delegate"]] += 1
        else:
            eval_f.write(json.dumps(sft, ensure_ascii=False) + "\n")
    for f in (scen_f, sft_f, eval_f):
        f.close()

    print(f"wrote {n_train} train + {n_eval} eval to {OUT_DIR}")
    print("person  :", dict(sorted(dist["person"].items())))
    print("urgency :", dict(sorted(dist["urgency"].items())))
    print("delegate:", dist["delegate"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=1500)
    ap.add_argument("--eval", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    build(args.train, args.eval, args.seed)
