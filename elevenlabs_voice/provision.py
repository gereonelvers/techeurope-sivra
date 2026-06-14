"""Provision the ElevenLabs ConvAI voice tier — idempotent.

Creates (or updates, if EL_AGENT_ID is already set) a ConvAI agent whose whole
job is to phone a human, explain a pending purchase decision, capture their
decision + feedback, and POST a HumanResolution back to the supervisor via a
server (webhook) tool `submit_decision`.

The decision text + who we're calling arrive per-call as dynamic variables:
  {{context}}      the pending decision text
  {{person}}       who we're addressing on the phone
  {{request_id}}   the supervisor's request_id (also used in the webhook URL)

Run:
  .venv/bin/python provision.py            # create/update the agent, print agent_id
  .venv/bin/python provision.py --telephony  # also try to set up the outbound SIP trunk

Reads ELEVEN_API_KEY (+ Telnyx vars) from the repo-root .env. Never prints secrets.
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
# The webhook tool POSTs the resolution to /resolve/{request_id}. ElevenLabs forbids the
# SAME parameter name across path + body, but the supervisor needs request_id in BOTH the
# URL path (routing) AND the body (its HumanResolution model). So the URL path placeholder
# is named `rid` (bound to the request_id dynamic variable) and `request_id` stays in the
# body (also bound to the same dynamic variable): different names, same value, no collision.
SUPERVISOR_BASE = os.environ.get("PUBLIC_BASE_URL", "https://sivra.io").rstrip("/")
RESOLVE_URL = f"{SUPERVISOR_BASE}/resolve/{{{{rid}}}}"

# Voice: "Charlotte" is a natural, warm multilingual voice. Override with EL_VOICE_ID.
VOICE_ID = os.environ.get("EL_VOICE_ID", "XB0fDUnXU5powFXDhCwa")  # Charlotte
LLM = os.environ.get("EL_LLM", "gemini-2.5-flash")
AGENT_NAME = os.environ.get("EL_AGENT_NAME", "sivra Quartermaster Voice")

# Telnyx (outbound SIP trunk -> PSTN)
TELNYX_API = "https://api.telnyx.com/v2"
TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY", "")
TELNYX_FROM = os.environ.get("TELNYX_FROM", "")
# The existing ElevenLabs<->Telnyx FQDN SIP connection ("VoxGuard-intern").
TELNYX_SIP_CONN_ID = os.environ.get("TELNYX_SIP_CONN_ID", "2900679085086738176")
TELNYX_OVP_ID = os.environ.get("TELNYX_OVP_ID", "2900274038037284437")  # "VoxGuard" outbound voice profile
# Telnyx ingests ElevenLabs SIP INVITEs at this host; ElevenLabs sends INVITEs to Telnyx here.
EL_TELNYX_OUTBOUND_HOST = os.environ.get("EL_TELNYX_OUTBOUND_HOST", "sip.telnyx.com")
TELNYX_SIP_USER = os.environ.get("TELNYX_SIP_USER", "voxguard")
TELNYX_SIP_PASS = os.environ.get("TELNYX_SIP_PASS", "")  # read from the connection if blank


def _h() -> dict:
    return {"xi-api-key": EL_KEY, "Content-Type": "application/json"}


# ── the system prompt + first message (use dynamic variables) ────────────────
SYSTEM_PROMPT = (
    "You are an autonomous buyer agent's assistant, phoning {{person}} to get a quick "
    "sign-off on a pending purchase decision. You are calling them on the phone, so keep "
    "every turn short and natural — this is a phone call, not an email.\n\n"
    "THE PENDING DECISION: {{context}}\n\n"
    "Run the call like this:\n"
    "1. You have already greeted them (see your first message). Briefly re-state the pending "
    "decision in one or two plain sentences if they need it.\n"
    "2. Answer any questions they have, plainly and honestly.\n"
    "3. Get their decision: approve, counter (with a specific euro amount), or decline. Read it "
    "back to confirm you heard it correctly.\n"
    "4. Then ask ONE quick feedback question: whether you reached the right person for this "
    "decision and whether the urgency felt right, or whether it should have gone to someone else "
    "or been more/less urgent. Keep it to one sentence.\n"
    "5. Call the submit_decision tool ONCE with everything: their resolution (and value if they "
    "countered), any notes, resolved_by = {{person}}, and the feedback — set rating='good' if you "
    "reached the right person at the right urgency, or rating='wrong' if not (and pass "
    "corrected_person / corrected_urgency when they tell you who should have been called or how "
    "urgent it really was).\n"
    "6. After the tool returns, briefly confirm it's recorded, thank them, and say goodbye.\n\n"
    "Do not call submit_decision until they have clearly decided AND you have read it back. "
    "Call it exactly once. The request_id for this decision is {{request_id}}."
)

FIRST_MESSAGE = (
    "Hi {{person}}, this is the buyer agent's assistant calling for a quick sign-off. "
    "I've got a pending purchase that needs your decision: {{context}} "
    "How would you like to proceed?"
)


def build_submit_decision_tool() -> dict:
    """The server (webhook) tool: POST a HumanResolution to the supervisor.

    Body matches shared/contracts/schema.py HumanResolution. The URL carries the
    {{request_id}} dynamic variable; resolved_by is the {{person}} we're calling.
    """
    return {
        "type": "webhook",
        "name": "submit_decision",
        "description": (
            "Record the human's final decision on the pending purchase AND the feedback signal "
            "about whether this was the right person/urgency to involve. Call this exactly ONCE, "
            "after they have clearly approved, countered, or declined, you've read it back, and "
            "you've asked the quick feedback question."
        ),
        "response_timeout_secs": 20,
        "api_schema": {
            "url": RESOLVE_URL,
            "method": "POST",
            "request_headers": {"Content-Type": "application/json"},
            # {{rid}} in the URL is a path parameter bound to the request_id dynamic
            # variable. Named `rid` (not `request_id`) so it doesn't collide with the
            # body's request_id field (ElevenLabs requires unique names across path/body).
            "path_params_schema": {
                "rid": {"type": "string", "dynamic_variable": "request_id"},
            },
            "request_body_schema": {
                "type": "object",
                "description": "A HumanResolution: the decision plus the reward signal.",
                "properties": {
                    # request_id appears in BOTH the URL path AND the body — the
                    # supervisor's HumanResolution model requires it in the body too.
                    "request_id": {
                        "type": "string",
                        "dynamic_variable": "request_id",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "The human's decision on the purchase.",
                        "enum": ["approve", "counter", "decline"],
                    },
                    "value": {
                        "type": "number",
                        "description": "The counter amount in euros (only when resolution=counter).",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional short note / reason the human gave for their decision.",
                    },
                    "resolved_by": {
                        # Bound to the {{person}} dynamic variable -> no description allowed.
                        "type": "string",
                        "dynamic_variable": "person",
                    },
                    "rating": {
                        "type": "string",
                        "description": (
                            "Feedback / reward signal: 'good' if you reached the right person at the "
                            "right urgency, 'wrong' if it was mis-routed (wrong person and/or urgency)."
                        ),
                        "enum": ["good", "wrong"],
                    },
                    "corrected_person": {
                        "type": "string",
                        "description": "Only when rating='wrong': who should have been called instead.",
                        "enum": ["buyer", "procurement_lead", "manager"],
                    },
                    "corrected_urgency": {
                        "type": "string",
                        "description": (
                            "Only when rating='wrong': how urgent this really was — 'async' (could "
                            "wait), 'urgent_push' (a text would do), or 'voice' (worth a phone call)."
                        ),
                        "enum": ["async", "urgent_push", "voice"],
                    },
                },
                "required": ["request_id", "resolution"],
            },
        },
    }


def build_conversation_config() -> dict:
    return {
        "agent": {
            "first_message": FIRST_MESSAGE,
            "language": "en",
            "dynamic_variables": {
                # Defaults used when a variable is not supplied (e.g. in the dashboard
                # test widget). Per-call values override these.
                "dynamic_variable_placeholders": {
                    "person": "the procurement lead",
                    "context": "a pending purchase decision",
                    "request_id": "unknown",
                }
            },
            "prompt": {
                "prompt": SYSTEM_PROMPT,
                "llm": LLM,
                "temperature": 0.2,
                "tools": [build_submit_decision_tool()],
                "built_in_tools": {
                    # Let the agent hang up cleanly once it has confirmed + said goodbye.
                    "end_call": {
                        "name": "end_call",
                        "description": "End the call once the decision is recorded and you've said goodbye.",
                    }
                },
            },
        },
        "tts": {
            "voice_id": VOICE_ID,
            # English agents must use a turbo/flash v2 model (API-enforced).
            "model_id": os.environ.get("EL_TTS_MODEL", "eleven_turbo_v2"),
            "stability": 0.45,
            "similarity_boost": 0.8,
            "speed": 1.0,
        },
        "asr": {"quality": "high", "user_input_audio_format": "ulaw_8000"},
        "conversation": {"max_duration_seconds": 600, "text_only": False},
    }


def create_or_update_agent() -> str:
    existing = os.environ.get("EL_AGENT_ID", "").strip()
    cfg = build_conversation_config()
    with httpx.Client(timeout=60) as c:
        if existing:
            print(f"Updating existing agent {existing} ...", file=sys.stderr)
            r = c.patch(
                f"{EL_API}/v1/convai/agents/{existing}",
                headers=_h(),
                json={"conversation_config": cfg, "name": AGENT_NAME},
            )
            r.raise_for_status()
            return existing
        print("Creating new agent ...", file=sys.stderr)
        r = c.post(
            f"{EL_API}/v1/convai/agents/create",
            headers=_h(),
            json={"name": AGENT_NAME, "conversation_config": cfg},
        )
        if r.status_code >= 400:
            print(f"create failed {r.status_code}: {r.text}", file=sys.stderr)
            r.raise_for_status()
        return r.json()["agent_id"]


def verify_agent(agent_id: str) -> None:
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{EL_API}/v1/convai/agents/{agent_id}", headers=_h())
        r.raise_for_status()
        data = r.json()
    prompt = data["conversation_config"]["agent"]["prompt"]
    tools = prompt.get("tools", [])
    tool_names = [t.get("name") for t in tools]
    submit = next((t for t in tools if t.get("name") == "submit_decision"), None)
    print("\n=== AGENT VERIFIED ===")
    print("agent_id:", agent_id)
    print("name:", data.get("name"))
    print("llm:", prompt.get("llm"))
    print("voice_id:", data["conversation_config"]["tts"].get("voice_id"))
    print("first_message:", data["conversation_config"]["agent"].get("first_message")[:80], "...")
    print("tools:", tool_names)
    if submit:
        print("submit_decision.url:", submit["api_schema"]["url"])
        print("submit_decision.method:", submit["api_schema"]["method"])
        props = submit["api_schema"]["request_body_schema"]["properties"]
        print("submit_decision.body fields:", list(props.keys()))
    else:
        print("!! submit_decision tool NOT found")


# ── Telephony: outbound SIP trunk phone number ───────────────────────────────
def setup_telephony(agent_id: str) -> None:
    """Attempt to wire Telnyx -> ElevenLabs for OUTBOUND PSTN, idempotently.

    Steps:
      1. Ensure the Telnyx FQDN SIP connection has an outbound voice profile (so
         Telnyx will route the ElevenLabs INVITE out to the PSTN).
      2. Import an OUTBOUND SIP-trunk phone number (+TELNYX_FROM) into ElevenLabs,
         pointing at Telnyx with the connection's digest credentials.
      3. Assign the agent to that number.
    Prints clear blockers (e.g. free-tier 403/402) instead of failing silently.
    """
    print("\n=== TELEPHONY SETUP ===", file=sys.stderr)
    tnx_h = {"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"}
    sip_pass = TELNYX_SIP_PASS
    with httpx.Client(timeout=40) as c:
        # 1) read the Telnyx SIP connection, grab creds, ensure outbound voice profile.
        r = c.get(f"{TELNYX_API}/fqdn_connections/{TELNYX_SIP_CONN_ID}", headers=tnx_h)
        if r.status_code < 400:
            conn = r.json()["data"]
            sip_user = conn.get("user_name") or TELNYX_SIP_USER
            sip_pass = sip_pass or conn.get("password") or ""
            ovp = (conn.get("outbound") or {}).get("outbound_voice_profile_id")
            print(f"Telnyx SIP conn {TELNYX_SIP_CONN_ID}: user={sip_user} ovp={ovp}", file=sys.stderr)
            if not ovp and TELNYX_OVP_ID:
                pr = c.patch(
                    f"{TELNYX_API}/fqdn_connections/{TELNYX_SIP_CONN_ID}",
                    headers=tnx_h,
                    json={"outbound": {"outbound_voice_profile_id": TELNYX_OVP_ID}},
                )
                print(f"attach outbound voice profile -> {pr.status_code}", file=sys.stderr)
        else:
            sip_user = TELNYX_SIP_USER
            print(f"could not read Telnyx conn ({r.status_code}); using defaults", file=sys.stderr)

        # 2) import the outbound SIP-trunk phone number into ElevenLabs.
        body = {
            "phone_number": TELNYX_FROM,
            "label": "sivra Quartermaster outbound (Telnyx)",
            "provider": "sip_trunk",
            "outbound_trunk_config": {
                "address": EL_TELNYX_OUTBOUND_HOST,  # ElevenLabs sends INVITE here (Telnyx)
                "transport": "tcp",
                "media_encryption": "disabled",
                "credentials": {"username": sip_user, "password": sip_pass},
            },
        }
        pr = c.post(f"{EL_API}/v1/convai/phone-numbers", headers=_h(), json=body)
        print(f"\nElevenLabs phone-number import -> HTTP {pr.status_code}", file=sys.stderr)
        if pr.status_code in (402, 403):
            print(
                "BLOCKER: ElevenLabs rejected the phone-number import — likely a paid-plan "
                "requirement on the free tier. Response: " + pr.text[:400],
                file=sys.stderr,
            )
            return
        if pr.status_code >= 400:
            print("phone-number import failed: " + pr.text[:500], file=sys.stderr)
            return
        phone_id = pr.json().get("phone_number_id")
        print("phone_number_id:", phone_id, file=sys.stderr)

        # 3) assign the agent to the number.
        ar = c.patch(
            f"{EL_API}/v1/convai/phone-numbers/{phone_id}",
            headers=_h(),
            json={"agent_id": agent_id},
        )
        print(f"assign agent -> HTTP {ar.status_code}", file=sys.stderr)
        print("\nTELEPHONY READY. Set EL_PHONE_NUMBER_ID=" + str(phone_id))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telephony", action="store_true", help="also set up the outbound SIP trunk")
    args = ap.parse_args()
    if not EL_KEY:
        print("ELEVEN_API_KEY missing", file=sys.stderr)
        sys.exit(1)
    agent_id = create_or_update_agent()
    verify_agent(agent_id)
    if args.telephony:
        setup_telephony(agent_id)
    print("\nAGENT_ID=" + agent_id)


if __name__ == "__main__":
    main()
