"""End-to-end check of the delegation supervisor — no server, no keys needed.

Runs the demo scenarios through /escalate, prints the routing table (beat #1:
right person + right urgency), then resolves two with human feedback to exercise
the reward loop (beat #3). Run:  python scripts/check_delegation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from demo.scenarios import SCENARIOS  # noqa: E402
from shared.contracts.schema import (  # noqa: E402
    HumanRating,
    HumanResolution,
    Resolution,
    RoutingDecision,
    TargetPerson,
    UrgencyTier,
)
from supervisor.app import app  # noqa: E402

client = TestClient(app)

# expected (person, urgency) per scenario index — guards against routing regressions
EXPECTED = {
    0: (TargetPerson.buyer, UrgencyTier.async_),
    1: (TargetPerson.procurement_lead, UrgencyTier.urgent_push),
    2: (TargetPerson.buyer, UrgencyTier.voice),
    3: (TargetPerson.buyer, UrgencyTier.async_),
    4: (TargetPerson.manager, UrgencyTier.voice),
    5: (TargetPerson.manager, UrgencyTier.voice),
}


def main() -> int:
    print("\n=== /health ===")
    print(client.get("/health").json())

    decisions: list[RoutingDecision] = []
    failures = 0
    print("\n=== Routing table (POST /escalate) ===")
    header = f"{'#':>2}  {'decision_type':<18} {'deleg':<5} {'person':<17} {'urgency':<12} {'extractor':<9}"
    print(header)
    print("-" * len(header))
    for i, scn in enumerate(SCENARIOS):
        r = client.post("/escalate", json=scn.model_dump(mode="json"))
        r.raise_for_status()
        d = RoutingDecision(**r.json())
        decisions.append(d)
        flag = ""
        if i in EXPECTED:
            exp_person, exp_urg = EXPECTED[i]
            ok = d.target_person == exp_person and d.urgency_tier == exp_urg
            if not ok:
                failures += 1
                flag = f"  <-- EXPECTED {exp_person.value}/{exp_urg.value}"
        ext = d.guardrail.extractor if d.guardrail else "n/a"
        print(
            f"{i:>2}  {scn.decision_type.value:<18} {str(d.should_delegate):<5} "
            f"{d.target_person.value:<17} {d.urgency_tier.value:<12} {ext:<9}{flag}"
        )

    # --- reward loop: resolve two delegations with human feedback ---
    print("\n=== Reward loop (POST /resolve) ===")
    # (a) a 'good' delegation
    good = decisions[1]
    res_a = client.post(
        f"/resolve/{good.request_id}",
        json=HumanResolution(
            request_id=good.request_id,
            resolved_by="procurement_lead",
            resolution=Resolution.counter,
            value=320.0,
            notes="counter at 320, our cap",
            latency_ms=8000,
            rating=HumanRating.good,
        ).model_dump(mode="json"),
    )
    res_a.raise_for_status()
    # (b) a 'wrong' delegation with a correction (should yield negative reward)
    wrong = decisions[0]
    res_b = client.post(
        f"/resolve/{wrong.request_id}",
        json=HumanResolution(
            request_id=wrong.request_id,
            resolved_by="buyer",
            resolution=Resolution.approve,
            latency_ms=240000,
            rating=HumanRating.wrong,
            corrected_urgency=UrgencyTier.urgent_push,
        ).model_dump(mode="json"),
    )
    res_b.raise_for_status()

    # show the logged reward records
    from supervisor.reward import REWARD_LOG

    print(f"reward log: {REWARD_LOG}")
    if REWARD_LOG.exists():
        import json

        for line in REWARD_LOG.read_text().splitlines()[-2:]:
            rec = json.loads(line)
            print(
                f"  reward={rec['reward']:+.2f}  predicted={rec['predicted']['target_person']}/"
                f"{rec['predicted']['urgency_tier']}  rating={rec['human']['rating']}"
            )

    # agent polls for resolution
    pend = client.get("/pending").json()
    print(f"\nopen delegations remaining: {len(pend)}")

    if failures:
        print(f"\n❌ {failures} routing mismatch(es)")
        return 1
    print("\n✅ all routing checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
