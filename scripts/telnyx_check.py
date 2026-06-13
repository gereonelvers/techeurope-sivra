"""Inspect the Telnyx account: phone numbers (+ capabilities), messaging profiles,
and Call Control / voice connections. Read-only. Run: python scripts/telnyx_check.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["TELNYX_API_KEY"]
H = {"Authorization": f"Bearer {KEY}"}


def get(path: str):
    r = httpx.get(f"https://api.telnyx.com/v2{path}", headers=H, timeout=20)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text


def summarize_numbers(body):
    for n in body.get("data", []):
        print(
            f"  • {n.get('phone_number')}  status={n.get('status')}  "
            f"messaging={n.get('messaging_profile_id') or 'UNASSIGNED'}  "
            f"connection={n.get('connection_id') or 'none'}"
        )


for path, label in [
    ("/phone_numbers", "PHONE NUMBERS"),
    ("/messaging_profiles", "MESSAGING PROFILES"),
    ("/connections", "CONNECTIONS (Call Control / voice apps)"),
]:
    code, body = get(path)
    print(f"\n=== {label}  [{code}] ===")
    if path == "/phone_numbers" and isinstance(body, dict):
        summarize_numbers(body)
    else:
        print(json.dumps(body, indent=2)[:1200] if isinstance(body, (dict, list)) else str(body)[:1200])
