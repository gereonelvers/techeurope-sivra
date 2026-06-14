"""Prove the INBOUND ordering agent + create_order tool with ZERO phone calls.

Uses ElevenLabs' simulate-conversation API: a scripted "employee" calls in and
asks to buy something; ElevenLabs runs the text conversation; when the agent calls
the `create_order` webhook tool, simulate-conversation MOCKS the tool (returns
"Tool Called.") and reports the captured tool arguments. We assert those args.

Because the real webhook (POST https://sivra.io/api/voice/intake) is the app's
EVENTUAL home and is not live yet, there is nothing to replay against — the point
of this test is to prove the AGENT extracts the fields and calls create_order with
the right shape (title ~ item, maxBudgetCents ~ budget in integer cents, etc.).

Run (repo .venv):
  EL_INBOUND_AGENT_ID=agent_xxx ../.venv/bin/python simulate_inbound.py
  ../.venv/bin/python simulate_inbound.py --agent-id agent_xxx
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

EL_API = "https://api.elevenlabs.io"
EL_KEY = os.environ.get("ELEVEN_API_KEY", "")
AGENT_ID = os.environ.get("EL_INBOUND_AGENT_ID", "").strip()
# A fake caller id for the simulation (bound to system__caller_id). Never a real number.
SIM_CALLER_ID = os.environ.get("SIM_CALLER_ID", "+10000000000")


def _h() -> dict:
    return {"xi-api-key": EL_KEY, "Content-Type": "application/json"}


def simulated_caller_prompt() -> str:
    return (
        "You are an employee who just phoned the company procurement line to order "
        "something. Speak naturally and briefly, like a real person on a quick phone "
        "call. You need a CORDLESS DRILL. Your budget is about 100 euros. You'd prefer "
        "a DeWalt if possible. When the assistant asks what you want to buy, say a "
        "cordless drill. When asked your budget, say around 100 euros. When asked for "
        "details, say you'd like a DeWalt if they can find one, new or refurbished is "
        "fine. When the assistant reads the order back to you, confirm it's correct. "
        "Then let them wrap up and say goodbye. Do not volunteer your phone number."
    )


def run_simulation(agent_id: str) -> dict:
    body = {
        "simulation_specification": {
            "simulated_user_config": {
                "first_message": "Hi, yeah, I need to order something.",
                "language": "en",
                "prompt": {
                    "prompt": simulated_caller_prompt(),
                    "llm": "gemini-2.5-flash",
                    "temperature": 0.3,
                },
            },
            # system__caller_id is normally injected by ElevenLabs on a real inbound
            # call; supply it here so the create_order tool's callerPhone binding has
            # a value during the simulation.
            "dynamic_variables": {
                "system__caller_id": SIM_CALLER_ID,
            },
        },
        "new_turns_limit": 25,
    }
    print("[1] running simulate-conversation (scripted caller: cordless drill ~100 EUR, DeWalt) ...")
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
    convo = sim.get("simulated_conversation", [])
    called = False
    captured: dict | None = None
    print("\n--- transcript ---")
    for turn in convo:
        role = turn.get("role")
        msg = (turn.get("message") or "").strip()
        if msg:
            print(f"  {role}: {msg[:170]}")
        for tc in turn.get("tool_calls") or []:
            name = tc.get("tool_name") or tc.get("name")
            raw = tc.get("params_as_json") or tc.get("tool_details") or tc.get("parameters")
            params = raw
            if isinstance(raw, str):
                try:
                    params = json.loads(raw)
                except Exception:
                    params = raw
            print(f"  >> TOOL CALL: {name}  params={json.dumps(params)[:300] if params else params}")
            if name == "create_order":
                called = True
                if isinstance(params, dict):
                    captured = params
        for tr in turn.get("tool_results") or []:
            name = tr.get("tool_name") or tr.get("name")
            res = tr.get("result_value") or tr.get("tool_details")
            print(f"  << TOOL RESULT: {name}  {json.dumps(res)[:200] if res else res}")
    print("------------------\n")
    print("create_order called during simulation:", called)
    return called, captured


def caller_phone_binding(agent_id: str) -> str | None:
    """Read back the agent's create_order tool: return callerPhone's bound dyn var.

    `callerPhone` is NOT an LLM-extracted field — it is auto-injected by ElevenLabs
    from the `system__caller_id` dynamic variable (the inbound SIP caller id) at
    webhook-dispatch time. simulate-conversation reports only the model-generated
    params, so callerPhone never appears in the captured args. The authoritative
    check is therefore the agent's tool CONFIG: is callerPhone bound to
    system__caller_id? We GET it back here.
    """
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{EL_API}/v1/convai/agents/{agent_id}", headers=_h())
        r.raise_for_status()
        data = r.json()
    tools = data["conversation_config"]["agent"]["prompt"].get("tools", [])
    tool = next((t for t in tools if t.get("name") == "create_order"), None)
    if not tool:
        return None
    props = tool["api_schema"]["request_body_schema"]["properties"]
    return props.get("callerPhone", {}).get("dynamic_variable")


def assert_args(args: dict, agent_id: str) -> bool:
    """Assert the captured create_order args match the scripted order."""
    ok = True

    def check(label: str, cond: bool, got) -> None:
        nonlocal ok
        status = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{status}] {label}  (got: {got!r})")

    title = str(args.get("title", "")).lower()
    desc = str(args.get("description", "")).lower()
    budget = args.get("maxBudgetCents")
    currency = args.get("currency")

    print("\n=== ASSERTIONS on captured create_order args ===")
    check("title mentions a drill", "drill" in title, args.get("title"))
    check(
        "maxBudgetCents ~ 10000 (100 EUR, integer cents)",
        isinstance(budget, int) and 5000 <= budget <= 15000,
        budget,
    )
    check("currency == 'EUR'", currency == "EUR", currency)
    check(
        "DeWalt captured (title or description)",
        "dewalt" in title or "dewalt" in desc,
        args.get("description") or args.get("title"),
    )
    # callerPhone is injected from system__caller_id at dispatch time (not by the
    # LLM, so it's absent from the simulated args) — assert the agent BINDING instead.
    binding = caller_phone_binding(agent_id)
    check(
        "callerPhone bound to system__caller_id (auto-injected on a real call)",
        binding == "system__caller_id",
        binding,
    )
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-id", default=AGENT_ID)
    args = ap.parse_args()
    if not EL_KEY or not args.agent_id:
        print("Need ELEVEN_API_KEY and EL_INBOUND_AGENT_ID (or --agent-id)", file=sys.stderr)
        sys.exit(1)
    sim = run_simulation(args.agent_id)
    called, captured = summarize(sim)
    if not called or captured is None:
        print("\nFAIL: agent did not call create_order with structured args.")
        sys.exit(2)
    ok = assert_args(captured, args.agent_id)
    print("\nRESULT:", "ALL ASSERTIONS PASSED" if ok else "SOME ASSERTIONS FAILED")
    sys.exit(0 if ok else 3)


if __name__ == "__main__":
    main()
