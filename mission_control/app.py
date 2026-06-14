"""sivra · mission control — the hero ops dashboard.

A control-room grid of up to ~100 buyer-agent tiles, each replaying one genuine
recorded computer-use run against the Kleinmarkt marketplace (search → filter →
view → cart → checkout → done) with a live screenshot, the current action, the
task goal, a status badge, a step counter and a green flash on success.

The page is driven entirely client-side from a single manifest. The server's job
is small and well-defined:

  GET  /                 the dashboard page (sivra design language)
  GET  /api/fleet        the LIVE-DATA HOOK (documented in README.md). Returns the
                         current fleet snapshot in the shape a real runtime can
                         push later; falls back to the bundled recorded replay.
  GET  /shots/<f>.jpg    bundled downscaled screenshots (static)
  GET  /health           liveness

`/api/fleet` is the seam for the runtime team. Today it synthesizes a snapshot
from the recorded manifest (staggered so the grid looks alive). To go live, set
FLEET_UPSTREAM to a URL that returns the same `{agents:[...], stats:{...}}` shape
and this service proxies it; on any error it transparently falls back to replay.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))

# Local dev convenience: load this dir's .env then the repo-root .env. In prod
# config comes from Railway service vars. We never print secrets.
load_dotenv(os.path.join(HERE, ".env"))
load_dotenv(os.path.join(HERE, "..", ".env"))

MANIFEST_PATH = os.path.join(HERE, "fleet.json")
SHOTS_DIR = os.path.join(HERE, "static", "shots")

# Optional live upstream. When set, /api/fleet proxies it (same response shape)
# and only falls back to the recorded replay on error / when ?replay=1.
FLEET_UPSTREAM = os.environ.get("FLEET_UPSTREAM", "").rstrip("/")

# How many tiles the grid shows by default (the famous "~100 at once").
DEFAULT_FLEET_SIZE = int(os.environ.get("FLEET_SIZE", "100"))

# ── live ingest (PUSH model) ──────────────────────────────────────────────────
# A local fleet (runtime/fleet.py, behind the orchestrator) can't be reached from
# Railway, so instead of us pulling it, IT pushes snapshots here. We keep the most
# recent pushed snapshot in memory; /api/fleet serves it while it is FRESH and
# transparently falls back to the recorded replay once it goes stale (or was never
# pushed). This is the live seam that needs no exposed localhost / tunnel.
INGEST_TTL_SECONDS = float(os.environ.get("INGEST_TTL_SECONDS", "12"))
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")  # optional shared secret

_LIVE_LOCK = threading.Lock()
_LIVE_SNAPSHOT: Optional[dict] = None
_LIVE_AT: float = 0.0  # wall-clock of last successful ingest


def _store_live(snapshot: dict) -> None:
    global _LIVE_SNAPSHOT, _LIVE_AT
    with _LIVE_LOCK:
        _LIVE_SNAPSHOT = snapshot
        _LIVE_AT = time.time()


def _live_snapshot(n: int) -> Optional[dict]:
    """Return the pushed snapshot iff it is fresh, sliced/decorated for the grid."""
    with _LIVE_LOCK:
        snap = _LIVE_SNAPSHOT
        age = time.time() - _LIVE_AT
    if not snap or age > INGEST_TTL_SECONDS:
        return None
    agents = list(snap.get("agents", []))[:n]
    # Reuse the replay stat block for the cost/headline gauges (corpus-true numbers
    # the slide relies on), but overlay the *live* active/done counts so the top bar
    # reflects the running fleet. The producer's own stats win where present.
    done_now = sum(1 for a in agents if a.get("status") in ("done", "checkout"))
    stats = _compute_stats(agents, done_now)
    stats.update({k: v for k, v in (snap.get("stats") or {}).items() if v is not None})
    return {
        "agents": agents,
        "stats": stats,
        "source": "live",
        "live_age": round(age, 2),
    }

with open(MANIFEST_PATH) as f:
    MANIFEST: dict[str, Any] = json.load(f)

TRAJ: list[dict] = MANIFEST["trajectories"]
META: dict = MANIFEST["meta"]

# Cost model for the "$ vs frontier" contrast. Our model is a tiny overfit Gemma
# served on Modal/E2B; a frontier computer-use API is ~3 orders of magnitude more
# per step. These are the numbers shown on the slide (clearly labelled estimates).
COST_OURS_PER_STEP = float(os.environ.get("COST_OURS_PER_STEP", "0.000042"))
COST_FRONTIER_PER_STEP = float(os.environ.get("COST_FRONTIER_PER_STEP", "0.011"))

app = FastAPI(title="sivra · mission control", version="1.0.0")

# Bundled screenshots (downscaled JPEGs produced by prep_data.py).
app.mount("/shots", StaticFiles(directory=SHOTS_DIR), name="shots")


# ── replay engine ────────────────────────────────────────────────────────────
# We turn the static manifest into a *live-looking* snapshot: each tile is pinned
# to a trajectory + a stable phase offset, so on every poll the whole grid has
# advanced one step and tiles sit at different points in their runs. When a tile's
# run finishes (done ✓) it flips to the next trajectory — exactly like a worker
# pool draining a task queue.

_STATUS_ORDER = ["searching", "filtering", "viewing", "cart", "checkout", "done"]


def _agent_assignment(n: int) -> list[dict]:
    """Deterministically assign n tiles to trajectories with phase offsets."""
    rng = random.Random(7)
    out = []
    for i in range(n):
        traj_idx = i % len(TRAJ)
        # spread starting steps so the grid isn't synchronized
        t = TRAJ[traj_idx]
        offset = rng.randint(0, max(t["n_steps"] - 1, 0))
        out.append({"slot": i, "traj_idx": traj_idx, "offset": offset, "cycle": 0})
    return out


# Stable assignment per fleet size (computed once).
_ASSIGN_CACHE: dict[int, list[dict]] = {}


def _assignment(n: int) -> list[dict]:
    if n not in _ASSIGN_CACHE:
        _ASSIGN_CACHE[n] = _agent_assignment(n)
    return _ASSIGN_CACHE[n]


# Global tick: advances ~1 step/second by wall clock so every client sees a
# coherent, always-moving grid even across page reloads.
TICK_SECONDS = float(os.environ.get("TICK_SECONDS", "1.6"))


def _replay_snapshot(n: int, tick: Optional[int] = None) -> dict:
    if tick is None:
        tick = int(time.time() / TICK_SECONDS)
    assign = _assignment(n)
    agents = []
    done_now = 0
    step_total = 0
    for a in assign:
        t = TRAJ[a["traj_idx"]]
        nsteps = max(t["n_steps"], 1)
        # which trajectory this slot is on now (cycle through the corpus as runs finish)
        pos = a["offset"] + tick
        cycles = pos // nsteps
        traj_idx = (a["traj_idx"] + cycles * 7) % len(TRAJ)  # +7: hop so neighbours differ
        t = TRAJ[traj_idx]
        nsteps = max(t["n_steps"], 1)
        step_i = pos % nsteps
        s = t["steps"][step_i] if t["steps"] else None
        if not s:
            continue
        status = s["status"]
        just_done = status == "done"
        if just_done:
            done_now += 1
        step_total += step_i + 1
        agents.append(
            {
                "agent_id": f"buyer-{a['slot']:03d}",
                "site": t["site_name"],
                "screenshot_url": f"/shots/{s['shot']}",
                "action": s["action"],
                "goal": t["goal"],
                "category": t["category"],
                "status": status,
                "step": step_i + 1,
                "n_steps": nsteps,
                "reward": t["reward"] if just_done else None,
                "success": t["success"],
            }
        )
    stats = _compute_stats(agents, done_now)
    return {"agents": agents, "stats": stats, "tick": tick, "source": "replay"}


def _compute_stats(agents: list[dict], done_now: int) -> dict:
    n = len(agents)
    active = sum(1 for a in agents if a["status"] != "done")
    # corpus-true headline numbers (399 real runs), plus live-grid gauges
    avg_steps = META["avg_steps"]
    total_steps = META["total_steps"]
    # tasks/min: assume ~12.35 steps/run at TICK_SECONDS/step across `active` tiles
    runs_in_flight = max(active, 1)
    secs_per_run = avg_steps * TICK_SECONDS
    tasks_per_min = round(runs_in_flight / secs_per_run * 60, 1)
    spend_ours = total_steps * COST_OURS_PER_STEP
    spend_frontier = total_steps * COST_FRONTIER_PER_STEP
    return {
        "active": active,
        "total_tiles": n,
        "done_now": done_now,
        "success_rate": META["success_rate"],
        "corpus_trajectories": META["corpus_trajectories"],
        "corpus_success": META["corpus_success"],
        "avg_steps": avg_steps,
        "total_steps": total_steps,
        "tasks_per_min": tasks_per_min,
        "model": META["model"],
        "cost_ours": round(spend_ours, 3),
        "cost_frontier": round(spend_frontier, 2),
        "cost_ratio": round(spend_frontier / spend_ours) if spend_ours else 0,
        "cost_ours_per_step": COST_OURS_PER_STEP,
        "cost_frontier_per_step": COST_FRONTIER_PER_STEP,
    }


# ── routes ───────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    with _LIVE_LOCK:
        live_age = (time.time() - _LIVE_AT) if _LIVE_SNAPSHOT else None
        live_n = len((_LIVE_SNAPSHOT or {}).get("agents", []))
    return {
        "ok": True,
        "bundled_trajectories": META["bundled_trajectories"],
        "shots": len(os.listdir(SHOTS_DIR)) if os.path.isdir(SHOTS_DIR) else 0,
        "upstream": bool(FLEET_UPSTREAM),
        "live": bool(live_age is not None and live_age <= INGEST_TTL_SECONDS),
        "live_age": round(live_age, 2) if live_age is not None else None,
        "live_agents": live_n,
    }


@app.post("/api/ingest")
async def ingest(request: Request):
    """PUSH seam: the live fleet (via the orchestrator) posts its latest
    {agents:[...], stats:{...}} snapshot here every step/second. We stash it and
    /api/fleet serves it while fresh. Optional `INGEST_TOKEN` shared secret is
    checked against the `x-ingest-token` header when set.

    A snapshot is just the same shape /api/fleet returns; minimally each agent
    needs agent_id, site, screenshot_url, action, goal, status, step, n_steps.
    """
    if INGEST_TOKEN and request.headers.get("x-ingest-token") != INGEST_TOKEN:
        return JSONResponse({"ok": False, "error": "bad token"}, status_code=401)
    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"bad json: {exc}"}, status_code=400)
    agents = body.get("agents")
    if not isinstance(agents, list):
        return JSONResponse({"ok": False, "error": "missing agents[]"}, status_code=400)
    _store_live(body)
    return {"ok": True, "agents": len(agents), "ttl": INGEST_TTL_SECONDS}


@app.get("/api/fleet")
async def fleet(
    n: int = Query(DEFAULT_FLEET_SIZE, ge=1, le=200),
    replay: int = Query(0, description="force recorded replay even if upstream set"),
):
    """Live-data hook. Returns {agents:[...], stats:{...}} (shape in README).

    Preference order (unless ?replay=1 forces the recording):
      1. a FRESH pushed snapshot (POST /api/ingest) — the live local fleet;
      2. FLEET_UPSTREAM proxy, if configured (legacy pull seam);
      3. the recorded replay (so the slide never goes blank).
    """
    if not replay:
        live = _live_snapshot(n)
        if live is not None:
            return JSONResponse(live)

    if FLEET_UPSTREAM and not replay:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f"{FLEET_UPSTREAM}/api/fleet", params={"n": n})
                r.raise_for_status()
                data = r.json()
                data.setdefault("source", "live")
                return JSONResponse(data)
        except Exception as exc:  # transparent fallback keeps the slide alive
            snap = _replay_snapshot(n)
            snap["source"] = "replay"
            snap["upstream_error"] = str(exc)[:140]
            return JSONResponse(snap)
    return JSONResponse(_replay_snapshot(n))


@app.get("/", response_class=HTMLResponse)
def index():
    from ui import render_page

    return HTMLResponse(render_page(META))
