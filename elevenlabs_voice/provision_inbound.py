"""Provision the ElevenLabs ConvAI INBOUND ordering tier — idempotent.

This is the sibling of provision.py (which sets up the OUTBOUND escalation agent).
Here we set up the *inbound* path: an employee CALLS our number and places a
purchase order by voice.

What it creates / reconciles (all idempotent — safe to re-run):
  1. A NEW inbound ordering ConvAI agent ("sivra Ordering"), kept
     SEPARATE from the outbound escalation agent (agent_8501kv0...). It greets the
     caller, asks what they want to buy + an approximate budget + key details,
     reads it back, calls the `create_order` webhook tool ONCE, confirms, and ends.
  2. The `create_order` server (webhook) tool:
        POST https://sivra.io/api/voice/intake
        header x-internal-token: $INTERNAL_API_TOKEN
        STATIC url, ALL data in the body:
          { callerPhone (bound to the system__caller_id dynamic variable),
            title, description?, maxBudgetCents (integer cents), currency:"EUR" }
     The app resolves caller -> user/org by phone, so the agent only supplies the
     caller id + the fields it extracted. No path templating (per the voice-tier
     memory: ElevenLabs webhook tools use a static URL with fields in the body).
  3. Inbound routing on the SHARED number +14472154920 (TELNYX_FROM):
       - ElevenLabs: PATCH the existing SIP-trunk phone number to add an
         inbound_trunk_config (so supports_inbound=true) and set its assigned_agent
         to the inbound ordering agent. A phone number's assigned_agent is the
         INBOUND-answering agent; OUTBOUND escalation calls are unaffected because
         the outbound-call API (app.py) passes its OWN agent_id in the request body
         and authenticates to Telnyx with the SIP credential — it never consults the
         number's assigned_agent. So one number does both: inbound ordering +
         outbound escalation.
       - Telnyx: repoint the number +14472154920 to the FQDN SIP connection
         "VoxGuard-intern" (FQDN sip.rtc.elevenlabs.io:5060) so that inbound PSTN
         calls TO the number are delivered as SIP INVITEs to ElevenLabs (which then
         hands the call to the assigned inbound agent). Without this, Telnyx routes
         the number to the old Gemini-Live bridge connection and the call never
         reaches ElevenLabs.

IMPORTANT — the app's intake endpoint (https://sivra.io/api/voice/intake) is the
app's EVENTUAL home: it is NOT live until apps/web is cut over to sivra.io. That's
expected. The simulate-conversation test (simulate_inbound.py) proves the agent +
tool wiring today; true end-to-end ordering is validated after the app deploys.

Run (use the repo .venv):
  ../.venv/bin/python provision_inbound.py              # create/update agent + tool, verify
  ../.venv/bin/python provision_inbound.py --routing    # + wire inbound routing (EL + Telnyx)

Reads ELEVEN_API_KEY, INTERNAL_API_TOKEN, TELNYX_API_KEY, TELNYX_FROM from the
repo-root .env. Never prints secrets.
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
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")

# The app's inbound-voice intake endpoint. STATIC url; all fields in the body.
# NOTE: this is the app's EVENTUAL home (after the apps/web cutover to sivra.io);
# it is not live yet — the simulate test proves the agent/tool until then.
INTAKE_BASE = os.environ.get("VOICE_INTAKE_BASE", "https://sivra.io").rstrip("/")
INTAKE_URL = f"{INTAKE_BASE}/api/voice/intake"

# Voice: "Charlotte" — natural, warm. Override with EL_VOICE_ID.
VOICE_ID = os.environ.get("EL_INBOUND_VOICE_ID", os.environ.get("EL_VOICE_ID", "XB0fDUnXU5powFXDhCwa"))
LLM = os.environ.get("EL_INBOUND_LLM", os.environ.get("EL_LLM", "gemini-2.5-flash"))
AGENT_NAME = os.environ.get("EL_INBOUND_AGENT_NAME", "sivra Ordering")

# The shared SIP-trunk number (does outbound escalation today; we add inbound).
INBOUND_NUMBER = os.environ.get("TELNYX_FROM", "+14472154920")
# The already-imported ElevenLabs phone-number id for +14472154920 (from provision.py).
EL_PHONE_NUMBER_ID = os.environ.get("EL_PHONE_NUMBER_ID", "phnum_5201kv0twb9cf3p901q4jds5t8tq").strip()

# Telnyx
TELNYX_API = "https://api.telnyx.com/v2"
TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY", "")
# The FQDN SIP connection whose single FQDN is sip.rtc.elevenlabs.io:5060 — i.e. the
# connection that delivers inbound SIP INVITEs to ElevenLabs. Repointing the number to
# this connection is what makes inbound PSTN -> ElevenLabs work.
TELNYX_EL_FQDN_CONN_ID = os.environ.get("TELNYX_SIP_CONN_ID", "2900679085086738176")


def _h() -> dict:
    return {"xi-api-key": EL_KEY, "Content-Type": "application/json"}


# ── system prompt + first message ────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are sivra's friendly procurement intake assistant. An employee has just "
    "CALLED you on the phone to place a purchase order by voice. Keep every turn "
    "short, warm, and natural — this is a phone call, not a form.\n\n"
    "Run the call like this:\n"
    "1. You have already greeted them (see your first message). Ask what they would "
    "like to buy.\n"
    "2. Once you know the item, get an APPROXIMATE budget (in euros) and any key "
    "details that matter — for example brand/model or whether refurbished/used is "
    "acceptable. Ask naturally; one short question at a time. Don't over-interrogate "
    "— a rough budget and one or two details is plenty.\n"
    "3. READ IT BACK in one sentence: the item, the approximate budget, and the key "
    "details, and ask them to confirm you've got it right. If they correct you, "
    "update and read it back once more.\n"
    "4. Once they confirm, call the create_order tool EXACTLY ONCE with:\n"
    "   - title: a short item title (e.g. 'cordless drill').\n"
    "   - description: the key details they gave (brand/model, condition, any notes). "
    "Omit if there were none.\n"
    "   - maxBudgetCents: their approximate budget converted to INTEGER CENTS in euros "
    "(e.g. 100 euros -> 10000, 79.50 euros -> 7950). Round sensibly if they were vague.\n"
    "   - currency is always 'EUR'.\n"
    "   (You do NOT need to ask for or supply their phone number — it is captured "
    "automatically from the call.)\n"
    "5. After the tool returns, confirm warmly: tell them the order's in and their "
    "team will get an update. Then thank them and say goodbye.\n\n"
    "Do not call create_order until they have confirmed the read-back. Call it exactly "
    "once. If they're unsure of a budget, gently suggest they give a rough ceiling."
)

FIRST_MESSAGE = (
    "Hi! You've reached sivra procurement. I can take a purchase request for you right "
    "now. What would you like to buy?"
)


def build_create_order_tool() -> dict:
    """The server (webhook) tool: POST a voice intake to the app.

    STATIC url (no path templating), all data in the body. callerPhone is bound to
    ElevenLabs' built-in `system__caller_id` dynamic variable (the calling number),
    so the app can resolve caller -> user/org by phone. The internal auth token rides
    a static request header.
    """
    return {
        "type": "webhook",
        "name": "create_order",
        "description": (
            "Create a purchase order from this inbound voice call. Call EXACTLY ONCE, "
            "after the caller has confirmed your read-back of the item, approximate "
            "budget, and key details."
        ),
        "response_timeout_secs": 20,
        "api_schema": {
            "url": INTAKE_URL,  # STATIC — all data goes in the body
            "method": "POST",
            "request_headers": {
                "Content-Type": "application/json",
                # Internal service auth (same scheme as the app's other internal routes).
                "x-internal-token": INTERNAL_API_TOKEN,
            },
            "request_body_schema": {
                "type": "object",
                "description": (
                    "An inbound voice order: the caller id plus the extracted fields. "
                    "The app resolves caller -> user/org by phone."
                ),
                "properties": {
                    "callerPhone": {
                        # Bound to the built-in caller-id dynamic variable -> no
                        # description allowed when a dynamic_variable is set.
                        "type": "string",
                        "dynamic_variable": "system__caller_id",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title of the item to buy, e.g. 'cordless drill'.",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Optional key details the caller gave: brand/model, condition "
                            "(new/refurbished/used), or any notes. Omit if none."
                        ),
                    },
                    "maxBudgetCents": {
                        "type": "integer",
                        "description": (
                            "The caller's approximate budget as INTEGER CENTS in euros "
                            "(100 euros -> 10000, 79.50 euros -> 7950)."
                        ),
                    },
                    "currency": {
                        "type": "string",
                        "description": "ISO currency code; always 'EUR' for these calls.",
                        "enum": ["EUR"],
                    },
                },
                "required": ["callerPhone", "title", "maxBudgetCents", "currency"],
            },
        },
    }


def build_conversation_config() -> dict:
    return {
        "agent": {
            "first_message": FIRST_MESSAGE,
            "language": "en",
            "dynamic_variables": {
                "dynamic_variable_placeholders": {
                    # system__caller_id is populated by ElevenLabs on a real inbound
                    # call; this placeholder is used in the dashboard/simulate widget.
                    "system__caller_id": "+10000000000",
                }
            },
            "prompt": {
                "prompt": SYSTEM_PROMPT,
                "llm": LLM,
                "temperature": 0.3,
                "tools": [build_create_order_tool()],
                "built_in_tools": {
                    "end_call": {
                        "name": "end_call",
                        "description": "End the call once the order is recorded and you've said goodbye.",
                    }
                },
            },
        },
        "tts": {
            "voice_id": VOICE_ID,
            "model_id": os.environ.get("EL_TTS_MODEL", "eleven_turbo_v2"),
            "stability": 0.45,
            "similarity_boost": 0.8,
            "speed": 1.0,
        },
        "asr": {"quality": "high", "user_input_audio_format": "ulaw_8000"},
        "conversation": {"max_duration_seconds": 600, "text_only": False},
    }


def create_or_update_agent() -> str:
    existing = os.environ.get("EL_INBOUND_AGENT_ID", "").strip()
    cfg = build_conversation_config()
    with httpx.Client(timeout=60) as c:
        if existing:
            print(f"Updating existing inbound agent {existing} ...", file=sys.stderr)
            r = c.patch(
                f"{EL_API}/v1/convai/agents/{existing}",
                headers=_h(),
                json={"conversation_config": cfg, "name": AGENT_NAME},
            )
            if r.status_code >= 400:
                print(f"update failed {r.status_code}: {r.text}", file=sys.stderr)
                r.raise_for_status()
            return existing
        print("Creating new inbound ordering agent ...", file=sys.stderr)
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
    tool = next((t for t in tools if t.get("name") == "create_order"), None)
    print("\n=== INBOUND AGENT VERIFIED ===")
    print("agent_id:", agent_id)
    print("name:", data.get("name"))
    print("llm:", prompt.get("llm"))
    print("voice_id:", data["conversation_config"]["tts"].get("voice_id"))
    fm = data["conversation_config"]["agent"].get("first_message") or ""
    print("first_message:", fm[:90], "...")
    print("tools:", tool_names)
    if tool:
        sch = tool["api_schema"]
        print("create_order.url:", sch["url"], "(static)" if "{{" not in sch["url"] else "(TEMPLATED!)")
        print("create_order.method:", sch["method"])
        hdrs = sch.get("request_headers", {})
        print("create_order.headers:", [k for k in hdrs.keys()])
        print("  x-internal-token present:", "x-internal-token" in hdrs)
        props = sch["request_body_schema"]["properties"]
        print("create_order.body fields:", list(props.keys()))
        cp = props.get("callerPhone", {})
        print("  callerPhone.dynamic_variable:", cp.get("dynamic_variable"))
        print("  maxBudgetCents.type:", props.get("maxBudgetCents", {}).get("type"))
        print("  required:", sch["request_body_schema"].get("required"))
    else:
        print("!! create_order tool NOT found")


# ── Inbound routing: ElevenLabs phone-number + Telnyx number repoint ──────────
def setup_inbound_routing(agent_id: str) -> None:
    """Wire inbound PSTN -> ElevenLabs -> the ordering agent, idempotently.

    a) ElevenLabs: PATCH the existing SIP-trunk number to add inbound_trunk_config
       (so supports_inbound=true) and set assigned_agent = the ordering agent.
       OUTBOUND escalation is untouched: app.py's outbound-call API passes its own
       agent_id and the SIP credential, never the number's assigned_agent.
    b) Telnyx: point the number's voice connection at the FQDN connection whose FQDN
       is sip.rtc.elevenlabs.io, so inbound calls are delivered to ElevenLabs.
    """
    print("\n=== INBOUND ROUTING SETUP ===", file=sys.stderr)

    # a) ElevenLabs side --------------------------------------------------------
    with httpx.Client(timeout=40) as c:
        body = {
            "agent_id": agent_id,  # the number's assigned (inbound-answering) agent
            "inbound_trunk_config": {
                # ACL-style: accept INVITEs from Telnyx (no per-call SIP auth here;
                # Telnyx forwards from its own IPs). Mirrors the existing inbound number.
                "allowed_addresses": ["0.0.0.0/0"],
                "media_encryption": "disabled",
            },
        }
        r = c.patch(
            f"{EL_API}/v1/convai/phone-numbers/{EL_PHONE_NUMBER_ID}",
            headers=_h(),
            json=body,
        )
        print(f"ElevenLabs PATCH phone-number ({EL_PHONE_NUMBER_ID}) -> HTTP {r.status_code}", file=sys.stderr)
        if r.status_code >= 400:
            print("  body: " + r.text[:500], file=sys.stderr)
        else:
            d = r.json()
            print(
                "  supports_inbound:", d.get("supports_inbound"),
                "| supports_outbound:", d.get("supports_outbound"),
                "| assigned_agent:", (d.get("assigned_agent") or {}).get("agent_id"),
                file=sys.stderr,
            )

    # b) Telnyx side: repoint the number to the ElevenLabs FQDN connection -------
    if not TELNYX_API_KEY:
        print("TELNYX_API_KEY missing — skipping Telnyx repoint.", file=sys.stderr)
        return
    tnx_h = {"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"}
    with httpx.Client(timeout=40) as c:
        # find the number record id
        r = c.get(
            f"{TELNYX_API}/phone_numbers",
            headers=tnx_h,
            params={"filter[phone_number]": INBOUND_NUMBER},
        )
        data = r.json().get("data", [])
        if not data:
            print(f"Telnyx: number {INBOUND_NUMBER} not found — skipping repoint.", file=sys.stderr)
            return
        num = data[0]
        nid = num["id"]
        cur_conn = num.get("connection_id")
        print(f"Telnyx number {INBOUND_NUMBER} (id {nid}) currently on connection {cur_conn}", file=sys.stderr)
        if str(cur_conn) == str(TELNYX_EL_FQDN_CONN_ID):
            print("  already on the ElevenLabs FQDN connection — inbound routing in place.", file=sys.stderr)
            return
        pr = c.patch(
            f"{TELNYX_API}/phone_numbers/{nid}",
            headers=tnx_h,
            json={"connection_id": TELNYX_EL_FQDN_CONN_ID},
        )
        print(f"  repoint -> connection {TELNYX_EL_FQDN_CONN_ID} -> HTTP {pr.status_code}", file=sys.stderr)
        if pr.status_code >= 400:
            print("  body: " + pr.text[:500], file=sys.stderr)
        else:
            nd = pr.json()["data"]
            print(
                "  now on connection:", nd.get("connection_id"),
                "(", nd.get("connection_name"), ")",
                file=sys.stderr,
            )
    print("\nINBOUND ROUTING READY. Set EL_INBOUND_AGENT_ID=" + agent_id)


def verify_routing() -> None:
    """GET the number back and print its inbound assignment (no call placed)."""
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{EL_API}/v1/convai/phone-numbers/{EL_PHONE_NUMBER_ID}", headers=_h())
        if r.status_code >= 400:
            print("verify_routing: GET failed", r.status_code, r.text[:300])
            return
        d = r.json()
    print("\n=== INBOUND ROUTING VERIFIED (ElevenLabs) ===")
    print("phone_number:", d.get("phone_number"))
    print("supports_inbound:", d.get("supports_inbound"))
    print("supports_outbound:", d.get("supports_outbound"), "(outbound escalation preserved)")
    print("assigned_agent (answers inbound):", (d.get("assigned_agent") or {}).get("agent_id"),
          "|", (d.get("assigned_agent") or {}).get("agent_name"))
    print("inbound_trunk:", json.dumps(d.get("inbound_trunk")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routing", action="store_true", help="also wire inbound routing (ElevenLabs + Telnyx)")
    args = ap.parse_args()
    if not EL_KEY:
        print("ELEVEN_API_KEY missing", file=sys.stderr)
        sys.exit(1)
    if not INTERNAL_API_TOKEN:
        print("WARNING: INTERNAL_API_TOKEN missing — the create_order tool will be created "
              "without the x-internal-token header value.", file=sys.stderr)
    agent_id = create_or_update_agent()
    verify_agent(agent_id)
    if args.routing:
        setup_inbound_routing(agent_id)
        verify_routing()
    print("\nINBOUND_AGENT_ID=" + agent_id)


if __name__ == "__main__":
    main()
