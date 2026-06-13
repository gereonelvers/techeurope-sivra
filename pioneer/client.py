"""Thin client for the Pioneer (Fastino) API — the one place every Pioneer call
lives. Endpoints confirmed against the live API:

    GET  /felix/training-jobs              list jobs            (works pre-billing)
    GET  /felix/datasets                   list datasets        (works pre-billing)
    POST /felix/datasets/upload/url        presigned upload     (needs a plan/card)
    POST /felix/datasets/upload/process    finish upload        (needs a plan/card)
    POST /felix/training-jobs              start fine-tune      (needs a plan/card)
    GET  /felix/training-jobs/{id}         poll status
    POST /inference                        GLiNER-style inference
    POST /v1/chat/completions              OpenAI-compatible (decoder inference)

NOTE: dataset write + training + inference currently 403 with
`card_verification_required` until the account subscribes at agent.pioneer.ai/billing.
Field names for the 3-step upload aren't fully documented; we read them defensively
and will confirm exact enums on the first real (billed) run.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import httpx


class PioneerError(RuntimeError):
    pass


class PioneerClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: float = 60.0):
        self.key = api_key or os.environ["PIONEER_API_KEY"]
        base = (base_url or os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai/v1")).rstrip("/")
        self.root = base[:-3] if base.endswith("/v1") else base  # https://api.pioneer.ai
        self.v1 = f"{self.root}/v1"
        self.h = {"X-API-Key": self.key}
        self.timeout = timeout

    def _req(self, method: str, url: str, **kw):
        r = httpx.request(method, url, headers={**self.h, **kw.pop("headers", {})}, timeout=self.timeout, **kw)
        if r.status_code >= 400:
            raise PioneerError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # ── reads (work without billing) ─────────────────────────────────────────
    def list_jobs(self):
        return self._req("GET", f"{self.root}/felix/training-jobs")

    def get_job(self, job_id: str):
        return self._req("GET", f"{self.root}/felix/training-jobs/{job_id}")

    def list_datasets(self):
        return self._req("GET", f"{self.root}/felix/datasets")

    # ── dataset upload (3-step) ──────────────────────────────────────────────
    def upload_dataset(self, name: str, jsonl_path: str, dataset_type: str = "training", data_format: str = "chat") -> str:
        body = {"dataset_name": name, "dataset_type": dataset_type, "type": data_format,
                "filename": Path(jsonl_path).name}
        res = self._req("POST", f"{self.root}/felix/datasets/upload/url",
                        headers={"Content-Type": "application/json"}, json=body)
        upload_url = res.get("upload_url") or res.get("url") or res.get("presigned_url")
        dataset_id = res.get("dataset_id") or res.get("id")
        if not upload_url or not dataset_id:
            raise PioneerError(f"unexpected upload-url response: {res}")
        with open(jsonl_path, "rb") as f:
            put = httpx.put(upload_url, content=f.read(), timeout=self.timeout)
        if put.status_code >= 400:
            raise PioneerError(f"S3 PUT failed: {put.status_code} {put.text[:200]}")
        self._req("POST", f"{self.root}/felix/datasets/upload/process",
                  headers={"Content-Type": "application/json"}, json={"dataset_id": dataset_id})
        return dataset_id

    def wait_dataset(self, dataset_id: str, poll: float = 5.0, timeout: float = 600.0) -> dict:
        deadline = None  # Date.now unavailable in some envs; rely on iteration count instead
        for _ in range(int(timeout // poll) + 1):
            ds = self._req("GET", f"{self.root}/felix/datasets/{dataset_id}")
            status = ds.get("status") or ds.get("data", {}).get("status")
            if status in ("ready", "complete"):
                return ds
            if status in ("failed", "error"):
                raise PioneerError(f"dataset {dataset_id} failed: {ds}")
            time.sleep(poll)
        raise PioneerError(f"dataset {dataset_id} not ready in time")

    # ── training ─────────────────────────────────────────────────────────────
    def create_training_job(self, model_name: str, base_model: str, dataset_name: str,
                            training_type: str = "lora", nr_epochs: int = 3,
                            learning_rate: float = 2e-4, extra: Optional[dict] = None):
        body = {"model_name": model_name, "base_model": base_model,
                "datasets": [{"name": dataset_name}], "training_type": training_type,
                "nr_epochs": nr_epochs, "learning_rate": learning_rate}
        if extra:
            body.update(extra)
        return self._req("POST", f"{self.root}/felix/training-jobs",
                         headers={"Content-Type": "application/json"}, json=body)

    def wait_job(self, job_id: str, poll: float = 30.0, timeout: float = 6 * 3600) -> dict:
        for _ in range(int(timeout // poll) + 1):
            job = self.get_job(job_id)
            status = job.get("status") or job.get("data", {}).get("status")
            print(f"  job {job_id} status={status}")
            if status in ("complete", "completed", "succeeded"):
                return job
            if status in ("failed", "stopped", "error"):
                raise PioneerError(f"job {job_id} ended: {status}")
            time.sleep(poll)
        raise PioneerError(f"job {job_id} not complete in time")

    # ── adaptive inference feedback (self-improvement loop) ───────────────────
    def feedback(self, inference_id: str, verdict: str, corrected_output: Optional[dict] = None):
        """Submit a correction so adaptive inference can retrain. Exact path TBD on
        first billed run; tries the documented shape."""
        body = {"verdict": verdict}
        if corrected_output is not None:
            body["corrected_output"] = corrected_output
        return self._req("POST", f"{self.root}/inferences/{inference_id}/feedback",
                         headers={"Content-Type": "application/json"}, json=body)
