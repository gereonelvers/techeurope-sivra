"""Live demo: emit buyer-agent escalations to a *running* supervisor and poll for
the human's reply (the contract a real buyer agent uses).

  Terminal 1:  uvicorn supervisor.app:app --reload      # (from repo root, venv active)
  Terminal 2:  python demo/simulate_agent.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from demo.scenarios import SCENARIOS  # noqa: E402
from shared.contracts.schema import RoutingDecision  # noqa: E402

BASE = os.getenv("SUPERVISOR_URL", "http://localhost:8000")


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        print("health:", c.get("/health").json())
        first_id = None
        for scn in SCENARIOS:
            r = c.post("/escalate", json=scn.model_dump(mode="json"))
            r.raise_for_status()
            d = RoutingDecision(**r.json())
            first_id = first_id or d.request_id
            print(
                f"-> {scn.decision_type.value:<18} deleg={d.should_delegate!s:<5} "
                f"{d.target_person.value}/{d.urgency_tier.value}"
            )

        print(f"\nPolling for a human resolution of {first_id[:8]} ...")
        print("(resolve it: "
              f"curl -X POST {BASE}/resolve/{first_id} "
              "-H 'content-type: application/json' "
              "-d '{\"request_id\":\"%s\",\"resolution\":\"approve\",\"rating\":\"good\"}')" % first_id)
        for _ in range(30):
            rr = c.get(f"/resolution/{first_id}")
            if rr.status_code == 200:
                print("resolved:", rr.json())
                return
            time.sleep(2)
        print("timed out waiting for a human (that's fine for a smoke test).")


if __name__ == "__main__":
    main()
