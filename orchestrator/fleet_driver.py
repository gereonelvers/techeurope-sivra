"""In-process fleet driver + Mission Control PUSH loop.

This is the glue that wires the three finished pieces together for ONE mission:

  1. spawns N buyer agents (reuses runtime/agent_loop.run_episode, one Playwright
     BrowserContext each) against the live marketplace via the Modal policy;
  2. every agent's per-step StepState lands in a shared FleetState (the same shape
     the dashboard consumes), and the escalation hook in agent_loop fires the
     human-in-the-loop round-trip to sivra.io;
  3. a PUSH loop POSTs the latest fleet snapshot to the DEPLOYED Mission Control's
     `POST /api/ingest` every ~1s, so the Railway dashboard shows the LIVE local
     fleet without anyone exposing localhost.

It deliberately mirrors runtime/fleet.py::run_fleet but (a) takes injected tasks
(from the goal parser) and (b) adds the pusher. runtime/fleet.py stays usable as
its own CLI; we just reuse its building blocks.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# Make runtime/ importable (it holds the finished agent loop + fleet state).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.path.join(REPO_ROOT, "runtime")
sys.path.insert(0, RUNTIME_DIR)

from agent_loop import (  # noqa: E402  (resolved at runtime via sys.path)
    MARKETPLACE_URL,
    VIEWPORT,
    MAX_STEPS,
    StepState,
    run_episode,
    _chromium_executable,
)
from fleet import FleetState  # noqa: E402
import audit_client  # noqa: E402

from playwright.async_api import async_playwright  # noqa: E402


@dataclass
class MissionState:
    """Live status of one mission, surfaced by the orchestrator's /status."""
    mission_id: str
    goal: str
    parsed: dict
    endpoint: str
    n: int
    ingest_url: str
    # org/order binding (optional; carried into escalations + audit events when set).
    org_id: Optional[str] = None
    order_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    status: str = "starting"          # starting | running | finished | error
    error: Optional[str] = None
    pushes: int = 0
    last_push_at: Optional[float] = None
    last_push_ok: Optional[bool] = None
    fleet: Optional[FleetState] = None
    escalations: dict = field(default_factory=dict)  # request_id -> {agent_id, reply_url, decision_type, resolved}

    def summary(self) -> dict:
        snap = self.fleet.snapshot() if self.fleet else {"agents": [], "stats": {}}
        agents = snap.get("agents", [])
        by_status: dict[str, int] = {}
        for a in agents:
            by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        return {
            "mission_id": self.mission_id,
            "goal": self.goal,
            "org_id": self.org_id,
            "order_id": self.order_id,
            "parsed": {k: self.parsed.get(k) for k in
                       ("category", "brand", "budget_eur", "recognised")},
            "status": self.status,
            "error": self.error,
            "n": self.n,
            "elapsed_s": round(time.time() - self.started_at, 1),
            "agents_total": len(agents),
            "by_status": by_status,
            "pushes": self.pushes,
            "last_push_ok": self.last_push_ok,
            "ingest_url": self.ingest_url,
            "escalations": list(self.escalations.values()),
        }


async def _push_loop(
    state: MissionState,
    client: httpx.AsyncClient,
    interval_s: float,
    stop: asyncio.Event,
    n_tiles: int,
    token: str = "",
):
    """Periodically POST the fleet snapshot to Mission Control /api/ingest."""
    headers = {"x-ingest-token": token} if token else {}
    while not stop.is_set():
        try:
            snap = state.fleet.snapshot(n_tiles) if state.fleet else {"agents": []}
            r = await client.post(state.ingest_url, json=snap, headers=headers, timeout=8.0)
            state.last_push_ok = (r.status_code == 200)
            state.pushes += 1
            state.last_push_at = time.time()
        except Exception:
            state.last_push_ok = False
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass
    # one final push so the dashboard reflects the terminal state
    try:
        snap = state.fleet.snapshot(n_tiles) if state.fleet else {"agents": []}
        await client.post(state.ingest_url, json=snap, headers=headers, timeout=8.0)
    except Exception:
        pass


async def run_mission(
    state: MissionState,
    tasks: list[dict],
    *,
    max_steps: int = MAX_STEPS,
    push_interval_s: float = 1.0,
    headless: bool = True,
    ingest_token: str = "",
):
    """Run the whole mission: launch the fleet, push live snapshots, collect
    escalations. Mutates `state` in place so the orchestrator can report status."""
    n = len(tasks)
    state.fleet = FleetState(state_file=None)
    state.status = "running"

    http_client = httpx.AsyncClient(timeout=120.0)
    push_client = httpx.AsyncClient(timeout=15.0)
    stop = asyncio.Event()
    pusher = asyncio.create_task(
        _push_loop(state, push_client, push_interval_s, stop, n_tiles=max(n, 1),
                   token=ingest_token)
    )

    # audit: the fleet started searching for this order (best-effort; no-op unless
    # APP_INTERNAL_URL + order_id are set).
    await audit_client.emit_event(
        state.order_id, "search_started", actor_type="system",
        message=f"Fleet launched: {n} agents for {state.goal!r}",
        data={"missionId": state.mission_id, "goal": state.goal, "n": n,
              "orgId": state.org_id},
        client=http_client,
    )

    exe = _chromium_executable()
    try:
        async with async_playwright() as p:
            launch_kwargs = {"args": ["--headless=new"]} if headless else {}
            if exe:
                launch_kwargs["executable_path"] = exe
            browser = await p.chromium.launch(**launch_kwargs)

            async def drive(i: int, task: dict):
                agent_id = f"buyer-{i:03d}"
                site = task["site"]
                spec = task["taskSpec"]
                category = spec.get("category", "?")
                # audit: an agent was spawned for this order.
                await audit_client.emit_event(
                    state.order_id, "agent_spawned", actor_type="system",
                    message=f"Spawned {agent_id} on {site}",
                    data={"agentId": agent_id, "site": site, "category": category,
                          "missionId": state.mission_id},
                    client=http_client,
                )
                context = await browser.new_context(
                    viewport=VIEWPORT, device_scale_factor=1, base_url=MARKETPLACE_URL
                )

                def on_state(st: StepState):
                    state.fleet.update(st, category=category, n_steps=max_steps)
                    # surface escalations to the orchestrator status view
                    esc = st.escalation
                    if esc and esc.get("request_id"):
                        rid = esc["request_id"]
                        rec = state.escalations.get(rid, {})
                        rec.update({
                            "request_id": rid,
                            "agent_id": st.agent_id,
                            "reply_url": esc.get("reply_url"),
                            "decision_type": esc.get("decision_type"),
                        })
                        if st.resolution:
                            rec["resolved"] = True
                            rec["resolution"] = st.resolution.get("resolution")
                        else:
                            rec.setdefault("resolved", False)
                        state.escalations[rid] = rec

                try:
                    return await run_episode(
                        context, state.endpoint, site, spec,
                        agent_id=agent_id, max_steps=max_steps,
                        on_state=on_state, http_client=http_client,
                        verbose=True,
                        org_id=state.org_id, order_id=state.order_id,
                    )
                except Exception as e:
                    print(f"[{agent_id}] driver error: {e}")
                    return None
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass

            await asyncio.gather(*(drive(i, t) for i, t in enumerate(tasks)))
            await browser.close()
        state.status = "finished"
    except Exception as e:
        state.status = "error"
        state.error = f"{type(e).__name__}: {e}"
        print(f"[mission {state.mission_id}] ERROR: {state.error}")
    finally:
        stop.set()
        try:
            await pusher
        except Exception:
            pass
        await http_client.aclose()
        await push_client.aclose()
