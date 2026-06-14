"""Mission orchestrator — the glue that turns a typed goal into a LIVE fleet.

Flow:
    user types a goal  ──POST /launch──▶  parse goal -> spawn N buyer agents
                                          (runtime/agent_loop) against the live
                                          marketplace, push live snapshots to the
                                          deployed Mission Control /api/ingest, and
                                          escalate human-decision moments to sivra.io.

Endpoints:
    GET  /              the launcher page (type a goal, hit "Launch mission")
    POST /launch        body {goal, n?} -> starts a mission (async) -> mission_id
    GET  /status        all missions' live status (parsed goal, by-status counts,
                         push health, escalations + reply links)
    GET  /status/{id}   one mission
    GET  /health        liveness + config (no secrets)

Config (env / repo-root .env):
    SERVE_ENDPOINT        Modal policy endpoint (default: the deployed one)
    MISSION_CONTROL_URL   dashboard base (default: the Railway URL) — we POST
                          {MISSION_CONTROL_URL}/api/ingest
    SUPERVISOR_URL        sivra.io (read by agent_loop for /escalate)
    INGEST_TOKEN          optional shared secret for /api/ingest
    MARKETPLACE_URL       default http://localhost:3000
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
# repo-root .env first, then a local override if present
load_dotenv(os.path.join(REPO_ROOT, ".env"))
load_dotenv(os.path.join(HERE, ".env"))

sys.path.insert(0, HERE)
from goal_parser import parse_goal, SITES, CATEGORIES  # noqa: E402
from fleet_driver import MissionState, run_mission  # noqa: E402
from ui import render_launcher  # noqa: E402

# ── config ────────────────────────────────────────────────────────────────────
DEFAULT_ENDPOINT = (
    "https://gereonelvers99--buyer-vision-serve-policy-infer.modal.run"
)
SERVE_ENDPOINT = os.environ.get("SERVE_ENDPOINT", DEFAULT_ENDPOINT)
MISSION_CONTROL_URL = os.environ.get(
    "MISSION_CONTROL_URL", "https://mission-control-production-332c.up.railway.app"
).rstrip("/")
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "https://sivra.io").rstrip("/")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")
MARKETPLACE_URL = os.environ.get("MARKETPLACE_URL", "http://localhost:3000")

DEFAULT_N = int(os.environ.get("MISSION_N", "12"))
MAX_N = int(os.environ.get("MISSION_MAX_N", "100"))

app = FastAPI(title="sivra · mission orchestrator", version="1.0.0")

# mission_id -> MissionState (kept in memory; one process per demo)
MISSIONS: dict[str, MissionState] = {}


class LaunchBody(BaseModel):
    goal: str
    n: Optional[int] = None
    endpoint: Optional[str] = None
    # org/order binding (optional, additive): when the app launches a mission it
    # passes these so escalations + audit events are scoped to the right org/order.
    # Omitted by the standalone launcher page -> mission runs exactly as before.
    orgId: Optional[str] = None
    orderId: Optional[str] = None


@app.get("/health")
def health():
    return {
        "ok": True,
        "serve_endpoint": SERVE_ENDPOINT,
        "mission_control": MISSION_CONTROL_URL,
        "supervisor": SUPERVISOR_URL,
        "marketplace": MARKETPLACE_URL,
        "missions": len(MISSIONS),
        "ingest_protected": bool(INGEST_TOKEN),
    }


@app.post("/launch")
async def launch(body: LaunchBody):
    goal = (body.goal or "").strip()
    if not goal:
        return JSONResponse({"ok": False, "error": "goal is required"}, status_code=400)
    n = max(1, min(int(body.n or DEFAULT_N), MAX_N))
    endpoint = (body.endpoint or SERVE_ENDPOINT).strip()

    parsed = parse_goal(goal, n)
    tasks = parsed["tasks"]

    mission_id = uuid.uuid4().hex[:8]
    state = MissionState(
        mission_id=mission_id,
        goal=goal,
        parsed=parsed,
        endpoint=endpoint,
        n=n,
        ingest_url=f"{MISSION_CONTROL_URL}/api/ingest",
        org_id=(body.orgId or None),
        order_id=(body.orderId or None),
    )
    MISSIONS[mission_id] = state

    # fire-and-forget: the mission runs in the background, pushing live snapshots
    asyncio.create_task(
        run_mission(state, tasks, ingest_token=INGEST_TOKEN)
    )

    return {
        "ok": True,
        "mission_id": mission_id,
        "goal": goal,
        "n": n,
        "parsed": {k: parsed.get(k) for k in ("category", "brand", "budget_eur", "recognised")},
        "sites": SITES,
        "endpoint": endpoint,
        "mission_control_url": MISSION_CONTROL_URL,
        "supervisor_pending_url": f"{SUPERVISOR_URL}/pending",
    }


@app.get("/status")
def status_all():
    return {
        "mission_control_url": MISSION_CONTROL_URL,
        "supervisor_pending_url": f"{SUPERVISOR_URL}/pending",
        "missions": [m.summary() for m in MISSIONS.values()],
    }


@app.get("/status/{mission_id}")
def status_one(mission_id: str):
    m = MISSIONS.get(mission_id)
    if not m:
        return JSONResponse({"ok": False, "error": "unknown mission"}, status_code=404)
    return m.summary()


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(render_launcher(
        mission_control_url=MISSION_CONTROL_URL,
        supervisor_url=SUPERVISOR_URL,
        endpoint=SERVE_ENDPOINT,
        default_n=DEFAULT_N,
        categories=CATEGORIES,
    ))
