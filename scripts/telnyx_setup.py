"""Idempotently provision Telnyx for SMS: ensure a 'sivra' messaging
profile exists and the TELNYX_FROM number is attached to it. Run once:
    python scripts/telnyx_setup.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["TELNYX_API_KEY"]
NUMBER = os.environ["TELNYX_FROM"]
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
BASE = "https://api.telnyx.com/v2"
PROFILE_NAME = "sivra"


def main() -> int:
    # 1. find or create the messaging profile
    profs = httpx.get(f"{BASE}/messaging_profiles", headers=H, timeout=20).json().get("data", [])
    prof = next((p for p in profs if p.get("name") == PROFILE_NAME), None)
    if prof is None:
        r = httpx.post(
            f"{BASE}/messaging_profiles",
            headers=H,
            json={"name": PROFILE_NAME, "whitelisted_destinations": ["US", "DE", "GB"]},
            timeout=20,
        )
        r.raise_for_status()
        prof = r.json()["data"]
        print(f"created messaging profile {prof['id']}")
    else:
        print(f"messaging profile exists {prof['id']}")
    profile_id = prof["id"]

    # 2. find the number's id
    nums = httpx.get(f"{BASE}/phone_numbers", headers=H, timeout=20).json().get("data", [])
    num = next((n for n in nums if n.get("phone_number") == NUMBER), None)
    if num is None:
        print(f"!! {NUMBER} not found on this account")
        return 1

    # 3. attach the number to the profile (if not already)
    if num.get("messaging_profile_id") == profile_id:
        print(f"{NUMBER} already attached to {profile_id}")
    else:
        r = httpx.patch(
            f"{BASE}/phone_numbers/{num['id']}/messaging",
            headers=H,
            json={"messaging_profile_id": profile_id},
            timeout=20,
        )
        r.raise_for_status()
        print(f"attached {NUMBER} -> messaging profile {profile_id}")
    print("\nSMS sending is ready (outbound). Inbound replies need a webhook (set later).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
