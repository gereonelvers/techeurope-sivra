"""
Parallel buyer-agent fleet runner.

Runs N agents concurrently (asyncio + one Playwright BrowserContext per agent),
each driving its OWN episode against the live marketplace with the Modal-served
Gemma 4 vision policy (serve_modal.py). Per-agent state is streamed in the shape
the mission_control dashboard consumes via its `/api/fleet` hook:

    {
      "agent_id":      "buyer-000",
      "site":          "site-a",
      "screenshot_url": "data:image/png;base64,...",   # or a /shots/ URL
      "screenshot_b64": "<base64 png>",                 # raw, for other consumers
      "action":        {"action":"click","x":..,"y":..},
      "goal":          "category=Phones, brand=OnePlus | site=site-a",
      "category":      "Phones",
      "status":        "running" | "done" | "error" | "timeout",
      "step":          3,
      "n_steps":       20,
      "reward":        0.0 | null
    }

Two sinks (both compatible with mission_control):
  1. A live FastAPI server exposing GET /api/fleet?n=N  -> {"agents":[...], "stats":{...}}.
     Point mission_control at it with:  FLEET_UPSTREAM=http://localhost:8900
  2. A JSONL snapshot file (--state-file) appended every tick for offline/dash use.

Usage:
    set -a; source ../.env; set +a
    .venv/bin/python fleet.py \
        --endpoint https://<workspace>--buyer-vision-serve-infer.modal.run \
        --n 8 --serve-port 8900 --state-file /tmp/fleet_state.jsonl

Local task sampling reuses agent/oracle/tasks.py against the seeded sqlite DB so
every agent gets a satisfiable {site, taskSpec}. If that import is unavailable a
small built-in task list is used.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Optional

import httpx
from playwright.async_api import async_playwright

# Local imports (same dir).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_loop import (  # noqa: E402
    MARKETPLACE_URL,
    VIEWPORT,
    MAX_STEPS,
    StepState,
    run_episode,
    goal_text,
    _chromium_executable,
)

SERVE_ENDPOINT = os.environ.get("SERVE_ENDPOINT", "")


# ----------------------------------------------------------------------------
# Task sampling: reuse agent/oracle/tasks.py if importable, else a static list.
# ----------------------------------------------------------------------------
def sample_tasks(n: int, seed: int = 0):
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    oracle_dir = os.path.join(repo, "agent", "oracle")
    try:
        sys.path.insert(0, oracle_dir)
        import tasks as oracle_tasks  # type: ignore

        ts = oracle_tasks.sample_tasks(n, seed=seed)
        return [{"site": t["site"], "taskSpec": t["taskSpec"]} for t in ts]
    except Exception as e:
        print(f"[fleet] task sampling fell back to static list ({e})")
        sites = ["site-a", "site-b", "site-c"]
        cats = ["Phones", "Laptops", "Bikes", "Cameras", "Audio", "Furniture"]
        out = []
        for i in range(n):
            out.append({"site": sites[i % 3], "taskSpec": {"category": cats[i % len(cats)]}})
        return out


# ----------------------------------------------------------------------------
# Shared live state (consumed by the /api/fleet server + JSONL writer).
# ----------------------------------------------------------------------------
# A 100-agent (Deep) snapshot embedding a full PNG data URI per tile is tens of
# MB — too big to push/serve each second. We embed screenshots for at most this
# many tiles (preferring the currently-active ones); the rest stream metadata
# only (still shown in the grid, just without a live frame).
SCREENSHOT_BUDGET = int(os.environ.get("FLEET_SHOT_BUDGET", "24"))

# Statuses that mean "this agent is actively browsing right now" — they win the
# screenshot budget over finished/idle tiles.
_ACTIVE_STATES = {"searching", "filtering", "viewing", "cart", "checkout", "running"}


def _format_action(action) -> Optional[str]:
    """Render a structured action dict as a compact human-readable string, so
    the fleet feed always emits a STRING for `action` (the dashboards render it
    directly — an object would crash a React client). Matches the replay feed's
    format ("click (x, y)", "done ✓", …)."""
    if action is None:
        return None
    if isinstance(action, str):
        return action or None
    if isinstance(action, dict):
        kind = action.get("action")
        x, y = action.get("x"), action.get("y")
        if kind == "click" and x is not None and y is not None:
            return f"click ({x}, {y})"
        if kind == "type" and action.get("text") is not None:
            return f'type "{str(action.get("text"))[:40]}"'
        if kind == "scroll" and action.get("dy") is not None:
            return f"scroll {action.get('dy')}"
        if kind in ("navigate_back", "back"):
            return "back"
        if kind == "done":
            item = action.get("item_id")
            return f"done #{item}" if item is not None else "done ✓"
        if kind == "escalate":
            return "escalate"
        if kind:
            return str(kind)
        return None
    return str(action)


class FleetState:
    def __init__(self, state_file: Optional[str] = None, embed_screens: bool = True):
        self.agents: dict[str, dict] = {}
        self.state_file = state_file
        self.embed_screens = embed_screens
        if state_file:
            # truncate at start
            open(state_file, "w").close()

    def update(self, st: StepState, category: str, n_steps: int):
        rec = {
            "agent_id": st.agent_id,
            "site": st.site,
            "action": _format_action(st.action),
            "goal": st.goal,
            "category": category,
            "status": st.status,
            "step": st.step,
            "n_steps": n_steps,
            "reward": st.reward,
            "screenshot_b64": st.screenshot_b64,
            # human-in-the-loop: carried through so the dashboard/pusher can show
            # the reply link + verdict on an `escalated` tile.
            "escalation": st.escalation,
            "resolution": st.resolution,
        }
        # mission_control reads `screenshot_url`; embed as a data URI so the
        # dashboard can render live frames with no extra static server.
        if self.embed_screens and st.screenshot_b64:
            rec["screenshot_url"] = f"data:image/png;base64,{st.screenshot_b64}"
        else:
            rec["screenshot_url"] = None
        self.agents[st.agent_id] = rec

        if self.state_file:
            # append a compact line (without the bulky b64) for tailing/inspection
            compact = {k: v for k, v in rec.items() if k not in ("screenshot_b64", "screenshot_url")}
            compact["ts"] = time.time()
            with open(self.state_file, "a") as f:
                f.write(json.dumps(compact) + "\n")

    def snapshot(self, n: Optional[int] = None) -> dict:
        agents = list(self.agents.values())
        if n is not None:
            agents = agents[:n]
        done = sum(1 for a in agents if a["status"] in ("done",))
        active = sum(1 for a in agents if a["status"] == "running")
        escalated = sum(1 for a in agents if a["status"] == "escalated")
        rewards = [a["reward"] for a in agents if a.get("reward") is not None]
        stats = {
            "active": active,
            "escalated": escalated,
            "total_tiles": len(agents),
            "done_now": done,
            "mean_reward": round(sum(rewards) / len(rewards), 4) if rewards else None,
            "source": "live",
        }
        return {"agents": self._bounded(agents), "stats": stats, "source": "live"}

    def _bounded(self, agents: list) -> list:
        """Keep the pushed/served payload small: always drop the redundant raw
        b64 (the dashboard renders screenshot_url), and embed screenshot_url for
        at most SCREENSHOT_BUDGET tiles — preferring actively-browsing, most-
        progressed ones. The rest keep all metadata but no live frame."""
        if len(agents) <= SCREENSHOT_BUDGET:
            keep = set(range(len(agents)))
        else:
            ranked = sorted(
                range(len(agents)),
                key=lambda i: (
                    1 if agents[i].get("status") in _ACTIVE_STATES else 0,
                    agents[i].get("step") or 0,
                ),
                reverse=True,
            )
            keep = set(ranked[:SCREENSHOT_BUDGET])
        out = []
        for i, a in enumerate(agents):
            a2 = {k: v for k, v in a.items() if k != "screenshot_b64"}
            if i not in keep:
                a2["screenshot_url"] = None
            out.append(a2)
        return out


# ----------------------------------------------------------------------------
# /api/fleet server (optional; lets mission_control proxy us via FLEET_UPSTREAM).
# ----------------------------------------------------------------------------
def build_app(state: FleetState):
    from fastapi import FastAPI, Query
    from fastapi.responses import JSONResponse

    api = FastAPI(title="buyer-fleet", version="1.0.0")

    @api.get("/health")
    def health():
        return {"ok": True, "agents": len(state.agents)}

    @api.get("/api/fleet")
    def fleet(n: int = Query(100, ge=1, le=500)):
        return JSONResponse(state.snapshot(n))

    return api


async def _serve_api(state: FleetState, port: int):
    import uvicorn

    config = uvicorn.Config(build_app(state), host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


# ----------------------------------------------------------------------------
# Fleet driver.
# ----------------------------------------------------------------------------
async def run_fleet(
    endpoint: str,
    n: int,
    seed: int = 0,
    max_steps: int = MAX_STEPS,
    serve_port: Optional[int] = None,
    state_file: Optional[str] = None,
    headless: bool = True,
):
    tasks = sample_tasks(n, seed=seed)
    state = FleetState(state_file=state_file)

    # one shared HTTP client (connection pool) for all agents' policy calls
    http_client = httpx.AsyncClient(timeout=120.0)

    # optional live /api/fleet server
    api_task = None
    if serve_port:
        api_task = asyncio.create_task(_serve_api(state, serve_port))
        print(f"[fleet] /api/fleet live at http://localhost:{serve_port}/api/fleet "
              f"(set mission_control FLEET_UPSTREAM=http://localhost:{serve_port})")

    exe = _chromium_executable()
    print(f"[fleet] launching {n} agents against {MARKETPLACE_URL} via {endpoint}")
    print(f"[fleet] chromium: {exe or '(playwright default)'}")

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
            context = await browser.new_context(
                viewport=VIEWPORT, device_scale_factor=1, base_url=MARKETPLACE_URL
            )

            def on_state(st: StepState):
                state.update(st, category=category, n_steps=max_steps)

            try:
                result = await run_episode(
                    context, endpoint, site, spec,
                    agent_id=agent_id, max_steps=max_steps,
                    on_state=on_state, http_client=http_client,
                    verbose=True,
                )
                return result
            except Exception as e:
                print(f"[{agent_id}] fleet-driver error: {e}")
                return None
            finally:
                try:
                    await context.close()
                except Exception:
                    pass

        t0 = time.time()
        results = await asyncio.gather(*(drive(i, t) for i, t in enumerate(tasks)))
        elapsed = time.time() - t0
        await browser.close()

    await http_client.aclose()

    # summarize
    ok = [r for r in results if r is not None]
    successes = sum(
        1 for r in ok if r.reward and r.reward.get("success")
    )
    scalars = [r.reward.get("scalar") for r in ok if r.reward and r.reward.get("scalar") is not None]
    print("\n===== FLEET SUMMARY =====")
    print(f"agents          : {len(results)}")
    print(f"completed        : {len(ok)}")
    print(f"reward.success   : {successes}/{len(ok)}")
    print(f"mean scalar      : {round(sum(scalars)/len(scalars),4) if scalars else None}")
    print(f"wall time        : {elapsed:.1f}s")
    for r in ok:
        rw = r.reward or {}
        print(f"  {r.agent_id} {r.site} {json.dumps(r.task_spec)} "
              f"status={r.status} steps={r.n_steps} "
              f"success={rw.get('success')} scalar={rw.get('scalar')}")

    if api_task:
        print(f"\n[fleet] /api/fleet still serving on :{serve_port}. Ctrl-C to stop.")
        try:
            await api_task
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=SERVE_ENDPOINT,
                    help="serve_modal.py infer endpoint URL")
    ap.add_argument("--n", type=int, default=4, help="number of concurrent agents")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--serve-port", type=int, default=None,
                    help="if set, expose GET /api/fleet on this port for mission_control")
    ap.add_argument("--state-file", default=None,
                    help="append per-step JSONL state snapshots here")
    args = ap.parse_args()

    if not args.endpoint:
        raise SystemExit("--endpoint (or SERVE_ENDPOINT env) is required")

    asyncio.run(run_fleet(
        endpoint=args.endpoint,
        n=args.n,
        seed=args.seed,
        max_steps=args.max_steps,
        serve_port=args.serve_port,
        state_file=args.state_file,
    ))


if __name__ == "__main__":
    main()
