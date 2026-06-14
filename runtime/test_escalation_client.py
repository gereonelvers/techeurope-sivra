"""Unit tests for runtime/escalation_client.py against a tiny in-thread mock HTTP
server (stdlib http.server). No pytest, no network: run directly.

    ../.venv/bin/python test_escalation_client.py     # from runtime/

Covers, for BOTH backends:
  * APP backend (APP_INTERNAL_URL set): asserts POST method/path/headers/body
    (camelCase + integer cents + x-internal-token) and the poll loop
    (GET .../escalations/{requestId}/resolution, 404 then 200).
  * SUPERVISOR fallback (APP_INTERNAL_URL unset): asserts POST {SUP}/escalate +
    poll GET {SUP}/resolution/{id}, and that the right backend is selected.
  * audit_client: best-effort event POST + result POST shapes; no-op when
    APP_INTERNAL_URL is unset and on a failing endpoint (never raises).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

# ── a tiny configurable mock server ────────────────────────────────────────────
class _Recorder:
    """Captures requests and scripts responses for one test."""
    def __init__(self):
        self.requests: list[dict] = []
        # number of resolution polls before we return 200 (simulate pending)
        self.polls_before_resolved = 1
        self._poll_count = 0
        # what the POST handler echoes back
        self.post_response: dict = {}
        self.resolution_body: dict = {}


def _make_handler(rec: _Recorder):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def _read_json(self):
            n = int(self.headers.get("content-length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw) if raw else {}
            except Exception:
                return {"_raw": raw.decode("utf-8", "replace")}

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            rec.requests.append({
                "method": "POST",
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": self._read_json(),
            })
            self._send(200, rec.post_response)

        def do_GET(self):
            rec.requests.append({
                "method": "GET",
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": None,
            })
            # resolution endpoints: 404 until polls_before_resolved reached, then 200
            if self.path.endswith("/resolution") or "/resolution/" in self.path:
                rec._poll_count += 1
                if rec._poll_count <= rec.polls_before_resolved:
                    self._send(404, {"status": "pending"})
                else:
                    self._send(200, rec.resolution_body)
            else:
                self._send(404, {"error": "not found"})

    return H


class MockServer:
    def __init__(self):
        self.rec = _Recorder()
        self.httpd = HTTPServer(("127.0.0.1", 0), _make_handler(self.rec))
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


# ── helpers ────────────────────────────────────────────────────────────────────
_results: list[tuple[bool, str]] = []


def check(cond: bool, label: str):
    _results.append((bool(cond), label))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")


def _reload_clients():
    """Re-import the client modules so module-level env snapshots refresh."""
    import importlib
    import escalation_client
    import audit_client
    importlib.reload(escalation_client)
    importlib.reload(audit_client)
    return escalation_client, audit_client


SAMPLE_REQUEST = {
    "request_id": "req-fixed-123",
    "agent_id": "buyer-007",
    "org_id": "org-acme",
    "order_id": "ord-42",
    "marketplace": "site-a",
    "decision_type": "approve_purchase",
    "situation_text": "Ready to buy a Phone for 420.",
    "item": {"title": "OnePlus", "listed_price": 420.0, "currency": "EUR"},
    "proposed_value": 420.0,
    "budget_cap": 400.0,
    "agent_confidence": 0.4,
}


# ── TEST 1: APP backend ─────────────────────────────────────────────────────────
def test_app_backend():
    print("\n[test] APP backend (APP_INTERNAL_URL set)")
    with MockServer() as srv:
        os.environ["APP_INTERNAL_URL"] = srv.url
        os.environ["INTERNAL_API_TOKEN"] = "secret-token-xyz"
        os.environ.pop("SUPERVISOR_URL", None)
        ec, _ = _reload_clients()
        srv.rec.polls_before_resolved = 1  # one 404 then 200
        srv.rec.post_response = {"requestId": "req-fixed-123", "urgency_tier": "async"}
        srv.rec.resolution_body = {"request_id": "req-fixed-123", "resolution": "approve", "value": 420.0}

        check(ec.use_app_backend(), "use_app_backend() True when APP_INTERNAL_URL set")

        async def run():
            async with httpx.AsyncClient() as client:
                return await ec.escalate(client, SAMPLE_REQUEST, poll_s=0.01, timeout_s=5.0)

        out = asyncio.run(run())

        posts = [r for r in srv.rec.requests if r["method"] == "POST"]
        gets = [r for r in srv.rec.requests if r["method"] == "GET"]
        check(len(posts) == 1, "exactly one POST")
        p = posts[0]
        check(p["path"] == "/api/internal/escalations", f"POST path == /api/internal/escalations (got {p['path']})")
        check(p["headers"].get("x-internal-token") == "secret-token-xyz", "x-internal-token header sent")
        b = p["body"]
        check(b.get("requestId") == "req-fixed-123", "body.requestId")
        check(b.get("orgId") == "org-acme", "body.orgId")
        check(b.get("orderId") == "ord-42", "body.orderId")
        check(b.get("decisionType") == "approve_purchase", "body.decisionType (camelCase)")
        check(b.get("situationText") == SAMPLE_REQUEST["situation_text"], "body.situationText")
        check(b.get("proposedValueCents") == 42000, f"body.proposedValueCents == 42000 (got {b.get('proposedValueCents')})")
        check(b.get("budgetCapCents") == 40000, f"body.budgetCapCents == 40000 (got {b.get('budgetCapCents')})")
        check(b.get("agentConfidence") == 0.4, "body.agentConfidence")
        check(b.get("item", {}).get("title") == "OnePlus", "body.item carried through")

        # poll loop: at least 2 GETs (one 404, one 200), to the right path
        check(len(gets) >= 2, f"polled at least twice (got {len(gets)})")
        check(all(g["path"] == "/api/internal/escalations/req-fixed-123/resolution" for g in gets),
              "GET poll path == /api/internal/escalations/{requestId}/resolution")
        check(all(g["headers"].get("x-internal-token") == "secret-token-xyz" for g in gets),
              "poll GETs carry x-internal-token")

        check(out["backend"] == "app", "out.backend == app")
        check(out["request_id"] == "req-fixed-123", "out.request_id")
        check((out["resolution"] or {}).get("resolution") == "approve", "out.resolution.resolution == approve")
        check(out["timed_out"] is False, "out.timed_out False")


# ── TEST 2: APP backend timeout (never resolves) ────────────────────────────────
def test_app_timeout():
    print("\n[test] APP backend timeout (resolution never 200)")
    with MockServer() as srv:
        os.environ["APP_INTERNAL_URL"] = srv.url
        os.environ["INTERNAL_API_TOKEN"] = "tok"
        ec, _ = _reload_clients()
        srv.rec.polls_before_resolved = 10_000  # always 404
        srv.rec.post_response = {"requestId": "req-fixed-123"}

        async def run():
            async with httpx.AsyncClient() as client:
                return await ec.escalate(client, SAMPLE_REQUEST, poll_s=0.01, timeout_s=0.08)

        out = asyncio.run(run())
        check(out["timed_out"] is True, "times out when resolution never returns 200")
        check(out["resolution"] is None, "resolution is None on timeout")


# ── TEST 3: SUPERVISOR fallback ─────────────────────────────────────────────────
def test_supervisor_fallback():
    print("\n[test] SUPERVISOR fallback (APP_INTERNAL_URL unset)")
    with MockServer() as srv:
        os.environ.pop("APP_INTERNAL_URL", None)
        os.environ["SUPERVISOR_URL"] = srv.url
        ec, _ = _reload_clients()
        srv.rec.polls_before_resolved = 1
        srv.rec.post_response = {"request_id": "sup-req-1", "should_delegate": True, "urgency_tier": "async"}
        srv.rec.resolution_body = {"request_id": "sup-req-1", "resolution": "decline"}

        check(not ec.use_app_backend(), "use_app_backend() False when APP_INTERNAL_URL unset")

        async def run():
            async with httpx.AsyncClient() as client:
                return await ec.escalate(client, SAMPLE_REQUEST, poll_s=0.01, timeout_s=5.0)

        out = asyncio.run(run())

        posts = [r for r in srv.rec.requests if r["method"] == "POST"]
        gets = [r for r in srv.rec.requests if r["method"] == "GET"]
        check(len(posts) == 1 and posts[0]["path"] == "/escalate",
              f"POST to /escalate (got {posts[0]['path'] if posts else None})")
        # fallback sends the snake_case DecisionRequest as-is (supervisor's schema)
        check(posts[0]["body"].get("decision_type") == "approve_purchase",
              "fallback body is snake_case DecisionRequest (decision_type)")
        check(any(g["path"] == "/resolution/sup-req-1" for g in gets),
              "GET poll path == /resolution/{request_id}")
        check(out["backend"] == "supervisor", "out.backend == supervisor")
        check((out["resolution"] or {}).get("resolution") == "decline", "out.resolution.resolution == decline")


# ── TEST 4: audit_client event + result ─────────────────────────────────────────
def test_audit_client():
    print("\n[test] audit_client event + result (best-effort)")
    with MockServer() as srv:
        os.environ["APP_INTERNAL_URL"] = srv.url
        os.environ["INTERNAL_API_TOKEN"] = "tok-audit"
        _, ac = _reload_clients()
        srv.rec.post_response = {"ok": True}

        async def run():
            async with httpx.AsyncClient() as client:
                ok_event = await ac.emit_event(
                    "ord-42", "candidate_found", actor_type="agent",
                    message="found one", data={"site": "site-a"}, client=client,
                )
                ok_result = await ac.post_result(
                    "ord-42", result_item_id=7, result_title="OnePlus",
                    result_price_cents=42000, receipt={"steps": 5}, client=client,
                )
                return ok_event, ok_result

        ok_event, ok_result = asyncio.run(run())
        posts = [r for r in srv.rec.requests if r["method"] == "POST"]
        ev = next((r for r in posts if r["path"] == "/api/internal/orders/ord-42/event"), None)
        rs = next((r for r in posts if r["path"] == "/api/internal/orders/ord-42/result"), None)

        check(ok_event is True, "emit_event returns True on 2xx")
        check(ev is not None, "event POST to /api/internal/orders/{id}/event")
        check(ev["headers"].get("x-internal-token") == "tok-audit", "event carries x-internal-token")
        check(ev["body"].get("type") == "candidate_found", "event body.type")
        check(ev["body"].get("actorType") == "agent", "event body.actorType (camelCase)")
        check(ev["body"].get("data", {}).get("site") == "site-a", "event body.data carried")

        check(ok_result is True, "post_result returns True on 2xx")
        check(rs is not None, "result POST to /api/internal/orders/{id}/result")
        check(rs["body"].get("resultPriceCents") == 42000, "result body.resultPriceCents")
        check(rs["body"].get("resultTitle") == "OnePlus", "result body.resultTitle")
        check(rs["body"].get("receipt", {}).get("steps") == 5, "result body.receipt carried")


# ── TEST 5: audit no-op when disabled / failing (never raises) ──────────────────
def test_audit_disabled_and_safe():
    print("\n[test] audit_client disabled (no APP_INTERNAL_URL) + failure-safe")
    os.environ.pop("APP_INTERNAL_URL", None)
    _, ac = _reload_clients()
    check(ac.enabled() is False, "audit disabled when APP_INTERNAL_URL unset")

    async def run_disabled():
        return await ac.emit_event("ord-1", "search_started", message="x")

    check(asyncio.run(run_disabled()) is False, "emit_event no-op (False) when disabled, no raise")

    # failure-safe: point at a dead port, must not raise, returns False
    os.environ["APP_INTERNAL_URL"] = "http://127.0.0.1:1"  # nothing listening
    _, ac = _reload_clients()

    async def run_fail():
        return await ac.emit_event("ord-1", "escalated", message="x")

    check(asyncio.run(run_fail()) is False, "emit_event returns False (not raise) on connection failure")
    os.environ.pop("APP_INTERNAL_URL", None)


def main():
    test_app_backend()
    test_app_timeout()
    test_supervisor_fallback()
    test_audit_client()
    test_audit_disabled_and_safe()

    passed = sum(1 for ok, _ in _results if ok)
    total = len(_results)
    print(f"\n================  {passed}/{total} checks passed  ================")
    if passed != total:
        print("FAILURES:")
        for ok, label in _results:
            if not ok:
                print(f"  - {label}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
