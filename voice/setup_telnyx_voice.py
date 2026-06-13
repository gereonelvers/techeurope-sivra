"""Idempotently provision the Telnyx Call Control Application for the voice tier.

What it does (all idempotent):
  1. Find-or-create a Call Control Application whose webhook_event_url points at
     the deployed voice service's `/telnyx/voice`.  The application's `id` IS the
     `connection_id` you pass to POST /v2/calls for outbound calls.
  2. Assign TELNYX_FROM to that connection so the number can place/receive calls
     on this application (PATCH /v2/phone_numbers/{id} { connection_id }).
  3. Print the application id / connection id so you can wire it into the service
     (CALL_CONTROL_APP_ID env var) — though app.py auto-discovers it at boot too.

Usage:
    python setup_telnyx_voice.py [--webhook-base https://your-voice.up.railway.app]

Reads TELNYX_API_KEY, TELNYX_FROM, and PUBLIC_VOICE_URL (or --webhook-base) from
the repo .env / environment.  Never prints secret values.
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

API = "https://api.telnyx.com/v2"
APP_NAME = "Quartermaster Voice (Gemini Live bridge)"


def _client(key: str) -> httpx.Client:
    return httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=30,
    )


def find_app(c: httpx.Client, webhook_url: str):
    """Return an existing app matching our name (idempotency key), else None."""
    r = c.get("/call_control_applications", params={"page[size]": 250})
    r.raise_for_status()
    for app in r.json().get("data", []):
        if app.get("application_name") == APP_NAME:
            return app
    return None


def ensure_app(c: httpx.Client, webhook_url: str) -> dict:
    existing = find_app(c, webhook_url)
    body = {
        "application_name": APP_NAME,
        "webhook_event_url": webhook_url,
        "webhook_api_version": "2",
        # Bidirectional media streaming is started explicitly via streaming_start,
        # so no inbound dialogflow/answering-machine config is needed here.
        "active": True,
    }
    if existing:
        app_id = existing["id"]
        # Keep the webhook URL fresh (e.g. after a redeploy to a new domain).
        if existing.get("webhook_event_url") != webhook_url:
            r = c.patch(f"/call_control_applications/{app_id}", json={"webhook_event_url": webhook_url})
            r.raise_for_status()
            print(f"[setup] updated webhook_event_url on existing app {app_id}")
        else:
            print(f"[setup] app already exists with correct webhook: {app_id}")
        return c.get(f"/call_control_applications/{app_id}").json()["data"]

    r = c.post("/call_control_applications", json=body)
    if r.status_code >= 400:
        print(f"[setup] create failed {r.status_code}: {r.text}", file=sys.stderr)
        r.raise_for_status()
    app = r.json()["data"]
    print(f"[setup] created Call Control Application: {app['id']}")
    return app


def ensure_outbound_profile(c: httpx.Client, connection_id: str) -> None:
    """A Call Control connection needs an Outbound Voice Profile to place calls
    (else Telnyx returns error D38). Attach the first enabled profile if none is set."""
    app = c.get(f"/call_control_applications/{connection_id}").json()["data"]
    if (app.get("outbound") or {}).get("outbound_voice_profile_id"):
        print("[setup] outbound voice profile already attached")
        return
    r = c.get("/outbound_voice_profiles", params={"page[size]": 50})
    r.raise_for_status()
    profiles = [p for p in r.json().get("data", []) if p.get("enabled", True)]
    if not profiles:
        print(
            "[setup] WARNING: no Outbound Voice Profile on this account. Create one in the "
            "Telnyx portal (Voice > Outbound Voice Profiles) or outbound calls fail with D38.",
            file=sys.stderr,
        )
        return
    pid = profiles[0]["id"]
    r = c.patch(
        f"/call_control_applications/{connection_id}",
        json={"outbound": {"outbound_voice_profile_id": pid}},
    )
    if r.status_code >= 400:
        print(f"[setup] WARNING: could not attach outbound profile ({r.status_code}): {r.text}", file=sys.stderr)
        return
    print(f"[setup] attached outbound voice profile {pid} ({profiles[0].get('name')}) to connection")


def assign_number(c: httpx.Client, connection_id: str, number: str) -> None:
    """Point TELNYX_FROM at this connection so outbound calls use this app."""
    r = c.get("/phone_numbers", params={"filter[phone_number]": number})
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        print(
            f"[setup] WARNING: {number} not found on this Telnyx account; "
            "skipping number assignment. Outbound calls still work via connection_id.",
            file=sys.stderr,
        )
        return
    pn = data[0]
    pn_id = pn["id"]
    current = str(pn.get("connection_id") or "")
    if current == str(connection_id):
        print(f"[setup] {number} already assigned to connection {connection_id}")
        return
    r = c.patch(f"/phone_numbers/{pn_id}", json={"connection_id": connection_id})
    if r.status_code >= 400:
        print(
            f"[setup] WARNING: could not assign {number} to connection "
            f"({r.status_code}): {r.text}. Outbound still works via connection_id.",
            file=sys.stderr,
        )
        return
    print(f"[setup] assigned {number} -> connection {connection_id}")


def main() -> int:
    load_dotenv()  # voice/.env
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))  # repo .env

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--webhook-base",
        default=os.getenv("PUBLIC_VOICE_URL", ""),
        help="Public https base of the deployed voice service (no trailing slash).",
    )
    args = ap.parse_args()

    key = os.environ.get("TELNYX_API_KEY")
    frm = os.environ.get("TELNYX_FROM")
    if not key or not frm:
        print("TELNYX_API_KEY and TELNYX_FROM are required.", file=sys.stderr)
        return 2

    base = args.webhook_base.rstrip("/")
    if not base:
        print(
            "No --webhook-base / PUBLIC_VOICE_URL set. Pass the deployed voice URL, e.g.\n"
            "  python setup_telnyx_voice.py --webhook-base https://voice-xxxx.up.railway.app",
            file=sys.stderr,
        )
        return 2
    if not base.startswith("https://"):
        print(f"webhook base must be https:// (got {base})", file=sys.stderr)
        return 2

    webhook_url = f"{base}/telnyx/voice"

    with _client(key) as c:
        app = ensure_app(c, webhook_url)
        connection_id = app["id"]
        ensure_outbound_profile(c, connection_id)
        assign_number(c, connection_id, frm)

    print("")
    print("=== Telnyx voice provisioning complete ===")
    print(f"application_name : {APP_NAME}")
    print(f"connection_id    : {connection_id}   (== Call Control Application id)")
    print(f"webhook_event_url: {webhook_url}")
    print(f"from number      : {frm}")
    print("")
    print("Set CALL_CONTROL_APP_ID in the voice service env to the connection_id above")
    print("(app.py also auto-discovers it by application_name at boot if unset).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
