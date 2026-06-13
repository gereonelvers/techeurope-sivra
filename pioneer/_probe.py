"""Throwaway probe to discover Pioneer's live API contract before committing the
client. Tries auth styles + lists models/jobs/datasets. Run: python pioneer/_probe.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["PIONEER_API_KEY"]
BASE = os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai/v1").rstrip("/")
ROOT = BASE[:-3] if BASE.endswith("/v1") else BASE  # https://api.pioneer.ai


def show(label, method, url, **kw):
    try:
        r = httpx.request(method, url, timeout=20, **kw)
        body = r.text
        if len(body) > 600:
            body = body[:600] + "…"
        print(f"\n### {label}: {method} {url}\n  -> {r.status_code}\n  {body}")
    except Exception as e:
        print(f"\n### {label}: {method} {url}\n  !! {type(e).__name__}: {e}")


xkey = {"X-API-Key": KEY}
bearer = {"Authorization": f"Bearer {KEY}"}

print(f"BASE={BASE}  ROOT={ROOT}  key=***{KEY[-4:]}")
show("models (X-API-Key)", "GET", f"{ROOT}/v1/models", headers=xkey)
show("models (Bearer)", "GET", f"{ROOT}/v1/models", headers=bearer)
show("training-jobs", "GET", f"{ROOT}/felix/training-jobs", headers=xkey)
show("datasets", "GET", f"{ROOT}/felix/datasets", headers=xkey)
show("models list (felix)", "GET", f"{ROOT}/felix/models", headers=xkey)

# Non-committal: ask for a presigned upload URL (no data uploaded yet) to learn the schema
show(
    "dataset upload-url",
    "POST",
    f"{ROOT}/felix/datasets/upload/url",
    headers={**xkey, "Content-Type": "application/json"},
    json={"dataset_name": "router_sft_probe", "dataset_type": "training", "type": "chat", "filename": "router_sft.jsonl"},
)
# Empty body -> expect 422 that reveals required training-job fields + allowed base_models
show(
    "training-jobs schema (empty body -> 422)",
    "POST",
    f"{ROOT}/felix/training-jobs",
    headers={**xkey, "Content-Type": "application/json"},
    json={},
)
