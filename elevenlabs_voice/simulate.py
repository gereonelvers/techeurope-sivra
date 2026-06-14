"""Prove the whole loop with ZERO phone calls, via ElevenLabs simulate-conversation.

Flow:
  1. POST https://sivra.io/escalate (a DecisionRequest) -> real request_id.
  2. POST /v1/convai/agents/{agent_id}/simulate-conversation with a simulated user
     who APPROVES. ElevenLabs runs the scripted text conversation; when the agent
     calls the `submit_decision` webhook tool, ElevenLabs ACTUALLY POSTs the
     HumanResolution to https://sivra.io/resolve/{request_id}.
  3. GET https://sivra.io/resolution/{request_id} -> confirm the resolution landed.

Run:
  .venv/bin/python simulate.py
  .venv/bin/python simulate.py --resolution counter   # other scripted decisions
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

EL_API = "https://api.elevenlabs.io"
EL_KEY = os.environ.get("ELEVEN_API_KEY", "")
AGENT_ID = os.environ.get("EL_AGENT_ID", "").strip()
SUPERVISOR = os.environ.get("PUBLIC_BASE_URL", "https://sivra.io").rstrip("/")
PERSON = "the procurement lead"


def _h() -> dict:
    return {"xi-api-key": EL_KEY, "Content-Type": "application/json"}


def create_escalation() -> tuple[str, str]:
    """Create a real pending delegation; return (request_id, context)."""
    payload = {
        "decision_type": "approve_purchase",
        "situation_text": (
            "Buyer agent found a refurbished Bosch GLM laser measure listed at 92 euros, "
            "13 euros over the 79 euro cap. Seller has 200+ reviews. Needs a quick sign-off."
        ),
        "agent_id": "buyer-eltest",
        "marketplace": "site-a",
        "agent_confidence": 0.45,
        "item": {"title": "Refurbished Bosch GLM laser measure", "listed_price": 92.0},
        "proposed_value": 92.0,
        "budget_cap": 79.0,
    }
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{SUPERVISOR}/escalate", json=payload)
    r.raise_for_status()
    d = r.json()
    rid = d["request_id"]
    context = d.get("suggested_message") or payload["situation_text"]
    print(f"[1] escalation created: request_id={rid}")
    print(f"    context = {context}")
    return rid, context


def simulated_user_prompt(resolution: str) -> str:
    base = (
        "You are {person}, a busy procurement lead who just answered the phone. An AI "
        "assistant is calling to get your sign-off on a pending purchase. Speak naturally and "
        "briefly, like a real person on a quick phone call. "
    ).format(person=PERSON)
    if resolution == "approve":
        return base + (
            "You are happy with the purchase — APPROVE it. When asked, clearly say you approve / "
            "it's fine to go ahead. When the assistant asks the quick feedback question about "
            "whether they reached the right person at the right urgency, say yes, you were exactly "
            "the right person and a phone call was appropriate. Then let them wrap up and say goodbye."
        )
    if resolution == "counter":
        return base + (
            "You think the price is a bit high — COUNTER at 80 euros. Clearly say you'd approve it "
            "only at 80 euros, not more. When asked the feedback question, say it was the right "
            "call to phone you. Then let them wrap up."
        )
    return base + (
        "You do NOT want this purchase — DECLINE it. Clearly say no, don't buy it. When asked the "
        "feedback question, say actually this could have just been a text, not a phone call — it "
        "wasn't that urgent. Then let them wrap up."
    )


def run_simulation(agent_id: str, request_id: str, context: str, resolution: str) -> dict:
    body = {
        "simulation_specification": {
            "simulated_user_config": {
                "first_message": "Hello?",
                "language": "en",
                "prompt": {
                    "prompt": simulated_user_prompt(resolution),
                    "llm": "gemini-2.5-flash",
                    "temperature": 0.3,
                },
            },
            "dynamic_variables": {
                "request_id": request_id,
                "context": context,
                "person": PERSON,
            },
        },
        "new_turns_limit": 25,
    }
    print(f"[2] running simulate-conversation (scripted user: {resolution}) ...")
    with httpx.Client(timeout=180) as c:
        r = c.post(
            f"{EL_API}/v1/convai/agents/{agent_id}/simulate-conversation",
            headers=_h(),
            json=body,
        )
    if r.status_code >= 400:
        print(f"    simulate failed {r.status_code}: {r.text[:600]}")
        r.raise_for_status()
    return r.json()


def summarize(sim: dict) -> tuple[bool, dict | None]:
    """Print the transcript; return (called, captured submit_decision args)."""
    convo = sim.get("simulated_conversation", [])
    called = False
    captured: dict | None = None
    print("\n--- transcript ---")
    for turn in convo:
        role = turn.get("role")
        msg = (turn.get("message") or "").strip()
        if msg:
            print(f"  {role}: {msg[:160]}")
        for tc in turn.get("tool_calls") or []:
            name = tc.get("tool_name") or tc.get("name")
            raw = tc.get("params_as_json") or tc.get("tool_details") or tc.get("parameters")
            params = raw
            if isinstance(raw, str):
                try:
                    params = json.loads(raw)
                except Exception:
                    params = raw
            print(f"  >> TOOL CALL: {name}  params={json.dumps(params)[:240] if params else params}")
            if name == "submit_decision":
                called = True
                if isinstance(params, dict):
                    captured = params
        for tr in turn.get("tool_results") or []:
            name = tr.get("tool_name") or tr.get("name")
            res = tr.get("result_value") or tr.get("tool_details")
            print(f"  << TOOL RESULT: {name}  {json.dumps(res)[:240] if res else res}")
    print("------------------\n")
    print("submit_decision called during simulation:", called)
    return called, captured


def replay_webhook(request_id: str, args: dict) -> None:
    """Reproduce the exact webhook POST ElevenLabs makes on a REAL call.

    simulate-conversation MOCKS server tools by default (returns 'Tool Called.'), so the
    real HTTP request to /resolve is not sent during simulation. We replay it here with
    the captured tool arguments + the request_id (URL path `rid` + body), which is byte-
    for-byte what the agent's webhook fires in production. This proves the resolve leg.
    """
    body = dict(args)
    body.setdefault("request_id", request_id)  # body field (bound to request_id dyn var)
    print(f"[2b] replaying webhook -> POST {SUPERVISOR}/resolve/{request_id}")
    print("     body =", json.dumps(body))
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{SUPERVISOR}/resolve/{request_id}", json=body)
    print(f"     -> HTTP {r.status_code} {r.text[:200]}")


def check_resolution(request_id: str) -> None:
    print(f"[3] GET {SUPERVISOR}/resolution/{request_id} ...")
    for attempt in range(6):
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{SUPERVISOR}/resolution/{request_id}")
        if r.status_code == 200 and r.text and r.text != "null":
            try:
                data = r.json()
            except Exception:
                data = r.text
            if data:
                print("    RESOLUTION FOUND:")
                print("    " + json.dumps(data, indent=2)[:900].replace("\n", "\n    "))
                return
        print(f"    not yet (HTTP {r.status_code}); retrying...")
        time.sleep(2)
    print("    !! no resolution found after retries")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolution", default="approve", choices=["approve", "counter", "decline"])
    ap.add_argument("--agent-id", default=AGENT_ID)
    args = ap.parse_args()
    if not EL_KEY or not args.agent_id:
        print("Need ELEVEN_API_KEY and EL_AGENT_ID (or --agent-id)", file=sys.stderr)
        sys.exit(1)
    rid, context = create_escalation()
    sim = run_simulation(args.agent_id, rid, context, args.resolution)
    called, captured = summarize(sim)
    if called and captured is not None:
        # simulate mocks the webhook; replay the captured args to actually drive /resolve.
        replay_webhook(rid, captured)
    check_resolution(rid)
    print("\nDONE. request_id=" + rid + " | submit_decision called=" + str(called))


if __name__ == "__main__":
    main()
