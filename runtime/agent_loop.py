"""
LIVE buyer-agent observe->act runtime.

Drives the seeded marketplace at http://localhost:3000 with the fine-tuned (or,
until the adapter lands, base) Gemma 4 vision policy served on Modal by
serve_modal.py. One episode:

    POST /api/episode {site, taskSpec}        -> set episode cookie, get targetItemId
    loop (<= MAX_STEPS):
        screenshot the Playwright page (1280x800, scale 1)
        -> POST <serve endpoint> {image_b64, goal}
        -> parse the next action JSON
        -> execute it in Playwright (click x,y / type / scroll / navigate_back / done)
    GET /api/reward?episodeId=...             -> structured reward

This mirrors agent/oracle/oracle.py but the actions come from the MODEL, not the
DOM. Everything is best-effort/robust: a failed step is logged and the loop
continues so one bad action never kills the episode.

The goal string handed to the model is byte-compatible with the training data
(vision_ft/build_dataset.py::_goal_text) so the policy sees its train distribution.

Usage (async, importable for the fleet):
    from agent_loop import run_episode, EpisodeResult

CLI (single episode smoke):
    set -a; source ../.env; set +a
    .venv/bin/python agent_loop.py \
        --endpoint https://<workspace>--buyer-vision-serve-infer.modal.run \
        --site site-a --category Phones --brand OnePlus
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

import httpx
from playwright.async_api import async_playwright, Error as PWError

# Centralized human-in-the-loop + audit clients (local imports; runtime/ is on
# sys.path when run as the fleet, and same-dir when run standalone).
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import escalation_client  # noqa: E402
import audit_client  # noqa: E402

# ----------------------------------------------------------------------------
# Constants mirrored from agent/oracle/config.py (NOT imported to avoid coupling).
# ----------------------------------------------------------------------------
MARKETPLACE_URL = os.environ.get("MARKETPLACE_URL", "http://localhost:3000")
VIEWPORT = {"width": 1280, "height": 800}
MAX_STEPS = 20
EPISODE_COOKIE = "episode_id"

# Where the serve_modal.py web endpoint lives. Override with --endpoint or env.
SERVE_ENDPOINT = os.environ.get("SERVE_ENDPOINT", "")

# ----------------------------------------------------------------------------
# Human-in-the-loop escalation (subsystem 2: the supervisor at sivra.io).
# When a buyer agent reaches a decision a human should own (about to commit a
# purchase, or a price over the budget cap), it does NOT auto-act: it POSTs a
# DecisionRequest to the supervisor, then polls for the human's HumanResolution
# and resumes accordingly (approve -> complete, decline -> move on, counter ->
# adjust). The agent's tile shows an `escalated` status while it waits.
# ----------------------------------------------------------------------------
SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "https://sivra.io").rstrip("/")
# Default budget cap (EUR) used to decide price_over_budget. Per-agent specs can
# override via taskSpec["maxPriceCents"].
DEFAULT_BUDGET_EUR = float(os.environ.get("BUYER_BUDGET_EUR", "400"))
# Seconds to wait for a human before giving up and moving on (timeout -> decline).
ESCALATION_TIMEOUT_S = float(os.environ.get("ESCALATION_TIMEOUT_S", "180"))
ESCALATION_POLL_S = float(os.environ.get("ESCALATION_POLL_S", "2.5"))
# Demo lever: force an escalation at this step so the human-in-the-loop path is
# demonstrable NOW with the (untrained) base model, which won't otherwise reach a
# real buy step. Set FORCE_ESCALATE_STEP=-1 to disable and rely on natural
# triggers only (which the trained adapter will hit). Default: fire at step 2.
FORCE_ESCALATE_STEP = int(os.environ.get("FORCE_ESCALATE_STEP", "2"))


def goal_text(site: str, task_spec: dict) -> str:
    """Reproduce vision_ft/build_dataset.py::_goal_text byte-for-byte.

    e.g. {"category":"Phones","brand":"OnePlus"} on site-a
         -> "category=Phones, brand=OnePlus | site=site-a"
    """
    spec = task_spec or {}
    parts = []
    if spec.get("category"):
        parts.append(f"category={spec['category']}")
    if spec.get("brand"):
        parts.append(f"brand={spec['brand']}")
    for k, v in spec.items():
        if k not in ("category", "brand"):
            parts.append(f"{k}={v}")
    goal = ", ".join(parts) if parts else "(unspecified)"
    if site:
        goal += f" | site={site}"
    return goal


# ----------------------------------------------------------------------------
# Per-step state record. Shape is compatible with the mission_control fleet hook.
# ----------------------------------------------------------------------------
@dataclass
class StepState:
    agent_id: str
    site: str
    goal: str
    step: int
    action: Optional[dict] = None
    status: str = "running"          # running | escalated | done | error | timeout
    reward: Optional[float] = None
    screenshot_b64: Optional[str] = None   # the frame the action was decided from
    raw: Optional[str] = None              # raw model text (debug)
    # human-in-the-loop fields (populated while/after an escalation):
    escalation: Optional[dict] = None      # {request_id, decision_type, reply_url, ...}
    resolution: Optional[dict] = None      # {resolution, value, resolved_by, ...} once human answers


@dataclass
class EpisodeResult:
    agent_id: str
    site: str
    task_spec: dict
    goal: str
    episode_id: Optional[str] = None
    target_item_id: Optional[int] = None
    steps: list = field(default_factory=list)   # list[dict] of actions taken
    n_steps: int = 0
    status: str = "running"
    reward: Optional[dict] = None
    error: Optional[str] = None
    escalated: bool = False
    escalation: Optional[dict] = None           # request_id / decision / resolution


# ----------------------------------------------------------------------------
# Serving client.
# ----------------------------------------------------------------------------
async def call_policy(
    client: httpx.AsyncClient, endpoint: str, image_b64: str, goal: str
) -> dict:
    """POST a screenshot + goal to the serve_modal.py endpoint; return the parsed
    response {"action": {...}, "raw": str, ...}. Raises on transport error."""
    resp = await client.post(
        endpoint,
        json={"image_b64": image_b64, "goal": goal},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


# ----------------------------------------------------------------------------
# Escalation to the human supervisor (sivra.io).
# ----------------------------------------------------------------------------
def _budget_eur(task_spec: dict) -> float:
    """Budget cap in EUR. taskSpec may carry maxPriceCents; else the default."""
    cents = (task_spec or {}).get("maxPriceCents")
    if isinstance(cents, (int, float)) and cents > 0:
        return float(cents) / 100.0
    return DEFAULT_BUDGET_EUR


def build_decision_request(
    *,
    agent_id: str,
    episode_id: Optional[str],
    site: str,
    goal: str,
    task_spec: dict,
    decision_type: str,
    item_title: str,
    proposed_value: float,
    budget_cap: float,
    agent_confidence: float,
    screenshot_b64: Optional[str] = None,
    org_id: Optional[str] = None,
    order_id: Optional[str] = None,
) -> dict:
    """Build the DecisionRequest body (shared/contracts/schema.py shape). Kept as a
    plain dict so this module stays dependency-light (the supervisor validates it).

    org_id / order_id bind the escalation to the calling organization + order so
    the app's internal API can persist it under the right scope (org scoping is
    mandatory per ARCHITECTURE.md). Both are optional for back-compat with the
    supervisor fallback, which ignores order_id and defaults org_id."""
    over = max(0.0, proposed_value - budget_cap)
    if decision_type == "price_over_budget":
        situation = (
            f"{item_title}: the seller wants €{proposed_value:.0f} — "
            f"€{over:.0f} over your €{budget_cap:.0f} cap. "
            f"Approve, counter, or decline?"
        )
    else:  # approve_purchase
        situation = (
            f"Ready to buy {item_title} for €{proposed_value:.0f} "
            f"(goal: {goal}). Approve the purchase, counter, or decline?"
        )
    body: dict = {
        "episode_id": episode_id,
        "agent_id": agent_id,
        "marketplace": site,
        "decision_type": decision_type,
        "situation_text": situation,
        "item": {"title": item_title, "listed_price": proposed_value, "currency": "EUR"},
        "proposed_value": proposed_value,
        "budget_cap": budget_cap,
        "agent_confidence": agent_confidence,
    }
    # org/order binding: set org_id only when provided so the supervisor's default
    # ("org-acme") still applies in the back-compat path; carry order_id for the app.
    if org_id:
        body["org_id"] = org_id
    if order_id:
        body["order_id"] = order_id
    # carry a screenshot URL if we can (data URI so the reply page can show context)
    if screenshot_b64:
        body["screenshot_url"] = f"data:image/png;base64,{screenshot_b64}"
    return body


async def escalate_to_human(
    client: httpx.AsyncClient,
    request_body: dict,
    *,
    timeout_s: float = ESCALATION_TIMEOUT_S,
    poll_s: float = ESCALATION_POLL_S,
    on_routed: Optional[Callable[[dict], Any]] = None,
    on_poll: Optional[Callable[[], Any]] = None,
) -> dict:
    """Escalate to the human + block on the resolution. Thin wrapper that delegates
    to escalation_client.escalate, which routes to the app internal API when
    APP_INTERNAL_URL is set and otherwise keeps today's supervisor /escalate flow.

    Returns {request_id, decision, resolution|None, reply_url, timed_out, error,
    backend}. Kept for back-compat: existing callers (and tests) import this name.
    on_routed(meta) fires once after the POST; on_poll() fires each poll tick."""
    return await escalation_client.escalate(
        client, request_body,
        timeout_s=timeout_s, poll_s=poll_s,
        on_routed=on_routed, on_poll=on_poll,
    )


# ----------------------------------------------------------------------------
# Action execution in Playwright.
# ----------------------------------------------------------------------------
async def _settle(page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass


async def execute_action(page, action: dict) -> bool:
    """Execute one model action. Returns True if this action ends the episode
    (a `done`). Robust: never raises -- failures are swallowed so the loop
    continues."""
    a = action.get("action")
    try:
        if a == "click":
            x = int(action.get("x", 0))
            y = int(action.get("y", 0))
            await page.mouse.click(x, y)
            await _settle(page)
        elif a == "type":
            text = str(action.get("text", ""))
            # Type into whatever is currently focused (mirrors the schema).
            await page.keyboard.type(text, delay=15)
            # A trained policy issues an explicit submit click next; we also press
            # Enter as a harmless nudge for search-style fields.
            try:
                await page.keyboard.press("Enter")
            except Exception:
                pass
            await _settle(page)
        elif a == "scroll":
            dy = int(action.get("dy", 0))
            await page.mouse.wheel(0, dy)
            await _settle(page)
        elif a == "navigate_back":
            await page.go_back()
            await _settle(page)
        elif a == "done":
            return True
    except PWError:
        pass
    except Exception:
        pass
    return False


# ----------------------------------------------------------------------------
# Episode API helpers (use the Playwright context request so the episode cookie
# is shared with the browser pages -- same trick as agent/oracle/run.py).
# ----------------------------------------------------------------------------
async def create_episode(context, site: str, task_spec: dict) -> dict:
    resp = await context.request.post(
        f"{MARKETPLACE_URL}/api/episode",
        data={"site": site, "taskSpec": task_spec},
    )
    if not resp.ok:
        raise RuntimeError(f"/api/episode {resp.status}: {await resp.text()}")
    return await resp.json()


async def fetch_reward(context, episode_id: str) -> Optional[dict]:
    resp = await context.request.get(
        f"{MARKETPLACE_URL}/api/reward", params={"episodeId": episode_id}
    )
    if not resp.ok:
        return None
    return await resp.json()


async def _screenshot_b64(page) -> str:
    png = await page.screenshot(
        clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]}
    )
    return base64.b64encode(png).decode()


# ----------------------------------------------------------------------------
# The observe->act loop for ONE episode.
# ----------------------------------------------------------------------------
async def run_episode(
    context,
    endpoint: str,
    site: str,
    task_spec: dict,
    agent_id: str = "agent-0",
    max_steps: int = MAX_STEPS,
    on_state: Optional[Callable[[StepState], Any]] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    verbose: bool = True,
    enable_escalation: bool = True,
    force_escalate_step: int = FORCE_ESCALATE_STEP,
    org_id: Optional[str] = None,
    order_id: Optional[str] = None,
    escalation_item_title: Optional[str] = None,
    escalation_proposed_value: Optional[float] = None,
) -> EpisodeResult:
    """Drive one full episode with the model. `on_state` (if given) is awaited
    with a StepState after every step so a dashboard can stream progress.

    org_id / order_id (optional) bind the episode to the calling organization +
    order: they're carried into the escalation payload (build_decision_request)
    and used as the subject of audit OrderEvents. Both default to None for
    back-compat — the existing demo runs unchanged.

    escalation_item_title / escalation_proposed_value (optional) let the caller
    supply a real-ish candidate for the escalation: a human-friendly item title
    (derived from the order goal) and a proposed price (EUR). Both default to None,
    in which case the existing behavior is used (item_title = goal_text, proposed =
    budget + 20 for an over-budget demo) — so back-compat callers are unchanged.

    Human-in-the-loop: at a decision moment (a forced demo step, or a natural buy
    `done`/over-budget) the agent escalates to the supervisor and BLOCKS on the
    human's answer instead of auto-acting. While blocked it emits an `escalated`
    StepState so its tile shows "awaiting human"; on resume it acts on the verdict.

    Audit: best-effort OrderEvents (candidate_found/escalated/purchased/completed)
    are posted to the app when APP_INTERNAL_URL is set and order_id is provided;
    they never block the run (see audit_client).
    """
    goal = goal_text(site, task_spec)
    result = EpisodeResult(
        agent_id=agent_id, site=site, task_spec=task_spec, goal=goal
    )

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient()
    budget = _budget_eur(task_spec)
    # Candidate label for the escalation: prefer a caller-supplied human title
    # (derived from the order goal, e.g. "Cordless drill"); else fall back to the
    # model goal text (the buyer's intent) as before.
    item_title = escalation_item_title or goal
    did_escalate = False  # only escalate once per episode (the demo decision)

    async def emit_local(state: StepState):
        if on_state is not None:
            try:
                maybe = on_state(state)
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                pass

    async def do_escalation(step: int, img_b64: Optional[str], proposed: float,
                            decision_type: str, confidence: float):
        """Run one escalation round-trip and emit escalated/resolved states."""
        nonlocal did_escalate
        did_escalate = True
        result.escalated = True
        body = build_decision_request(
            agent_id=agent_id, episode_id=result.episode_id, site=site, goal=goal,
            task_spec=task_spec, decision_type=decision_type, item_title=item_title,
            proposed_value=proposed, budget_cap=budget,
            agent_confidence=confidence, screenshot_b64=img_b64,
            org_id=org_id, order_id=order_id,
        )
        # audit: a human sign-off was requested (best-effort; never blocks)
        await audit_client.emit_event(
            order_id, "escalated", actor_type="agent",
            message=f"{agent_id} escalated ({decision_type}) for sign-off",
            data={"agentId": agent_id, "decisionType": decision_type,
                  "proposedValueCents": int(round(proposed * 100)),
                  "budgetCapCents": int(round(budget * 100)), "site": site},
            client=client,
        )
        # Show "escalated" on the tile while the human decides.
        esc_state = StepState(
            agent_id=agent_id, site=site, goal=goal, step=step,
            action={"action": "escalate", "decision_type": decision_type,
                    "proposed": proposed, "budget": budget},
            status="escalated", screenshot_b64=img_b64,
        )

        async def _on_routed(meta: dict):
            esc_state.escalation = {
                "request_id": meta.get("request_id"),
                "reply_url": meta.get("reply_url"),
                "decision_type": decision_type,
                "proposed_value": proposed,
                "budget_cap": budget,
            }
            await emit_local(esc_state)
            if verbose:
                print(f"[{agent_id}] ESCALATED ({decision_type}) "
                      f"req={meta.get('request_id')} reply={meta.get('reply_url')}")

        async def _on_poll():
            # keep the tile alive/blinking while we wait
            await emit_local(esc_state)

        outcome = await escalate_to_human(
            client, body, on_routed=_on_routed, on_poll=_on_poll,
        )
        result.escalation = outcome
        esc_state.escalation = {
            "request_id": outcome.get("request_id"),
            "reply_url": outcome.get("reply_url"),
            "decision_type": decision_type,
        }
        res = outcome.get("resolution")
        esc_state.resolution = res
        await emit_local(esc_state)
        if verbose:
            verdict = (res or {}).get("resolution") if res else (
                "timeout" if outcome.get("timed_out") else outcome.get("error"))
            print(f"[{agent_id}] HUMAN VERDICT: {verdict}")
        return outcome

    page = await context.new_page()
    await page.set_viewport_size(VIEWPORT)

    try:
        # 1. create episode (shared cookie) ---------------------------------
        ep = await create_episode(context, site, task_spec)
        result.episode_id = ep.get("episodeId")
        result.target_item_id = ep.get("targetItemId")
        if verbose:
            print(f"[{agent_id}] episode={result.episode_id} target={result.target_item_id} goal={goal!r}")

        # 2. land on the site -----------------------------------------------
        await page.goto(f"{MARKETPLACE_URL}/{site}", wait_until="domcontentloaded")
        await _settle(page)

        # 3. observe -> act loop --------------------------------------------
        for step in range(max_steps):
            try:
                img_b64 = await _screenshot_b64(page)
            except Exception as e:
                result.error = f"screenshot-failed: {e}"
                break

            # observe: ask the policy
            try:
                policy_out = await call_policy(client, endpoint, img_b64, goal)
            except Exception as e:
                result.error = f"policy-call-failed: {e}"
                if verbose:
                    print(f"[{agent_id}] step {step}: policy call failed: {e}")
                state = StepState(
                    agent_id=agent_id, site=site, goal=goal, step=step,
                    status="error", screenshot_b64=img_b64,
                )
                await emit_local(state)
                break

            action = policy_out.get("action") or {}
            raw = policy_out.get("raw")
            result.steps.append(action)
            result.n_steps = step + 1

            if verbose:
                print(f"[{agent_id}] step {step}: {json.dumps(action)}  (raw={raw!r})")

            state = StepState(
                agent_id=agent_id, site=site, goal=goal, step=step,
                action=action, status="running",
                screenshot_b64=img_b64, raw=raw,
            )
            await emit_local(state)

            # ── human-in-the-loop decision point ──────────────────────────────
            # Two triggers: (a) a forced demo step so the path is demonstrable now
            # with the base model; (b) a NATURAL buy — the model emitted `done`
            # (it selected a final candidate). Either way we escalate and block on
            # the human, then act on the verdict instead of auto-buying.
            is_buy = action.get("action") == "done"
            forced = (
                enable_escalation and not did_escalate
                and force_escalate_step >= 0 and step == force_escalate_step
            )
            # audit: the model picked a final candidate (natural buy `done`).
            if is_buy:
                await audit_client.emit_event(
                    order_id, "candidate_found", actor_type="agent",
                    message=f"{agent_id} selected a candidate to purchase",
                    data={"agentId": agent_id, "site": site,
                          "itemId": action.get("item_id"), "goal": goal},
                    client=client,
                )
            if enable_escalation and not did_escalate and (forced or is_buy):
                decision_type = "approve_purchase" if is_buy else "price_over_budget"
                # proposed price: for a real buy we'd read it off the listing; with
                # the base model we use a value just over the cap so the supervisor's
                # over-budget routing fires (clearly a placeholder until the adapter).
                # A caller (e.g. the cloud mission) may supply a real-ish proposed
                # value derived from the order budget; honor it when present.
                if escalation_proposed_value is not None:
                    proposed = float(escalation_proposed_value)
                else:
                    proposed = budget + 20.0 if decision_type == "price_over_budget" else budget
                confidence = float(policy_out.get("confidence", 0.4) or 0.4)
                outcome = await do_escalation(
                    step, img_b64, proposed, decision_type, confidence
                )
                res = (outcome.get("resolution") or {})
                verdict = res.get("resolution")  # approve | counter | decline | None
                if verdict == "decline" or (verdict is None and outcome.get("timed_out")):
                    # human said no / no answer in time -> abandon this candidate
                    result.status = "declined" if verdict == "decline" else "timeout"
                    break
                # approve / counter -> resume. For a natural buy, complete it; for a
                # forced over-budget demo, keep shopping (the model continues).
                if is_buy:
                    result.status = "done"
                    # audit: human approved -> the purchase goes through.
                    await audit_client.emit_event(
                        order_id, "purchased", actor_type="agent",
                        message=f"{agent_id} purchased the approved candidate",
                        data={"agentId": agent_id, "site": site,
                              "itemId": action.get("item_id"),
                              "valueCents": int(round(proposed * 100)),
                              "verdict": verdict},
                        client=client,
                    )
                    break
                # else: fall through and keep acting (resume)

            # act
            is_done = await execute_action(page, action)
            if is_done:
                result.status = "done"
                break
        else:
            result.status = "timeout"

        # 4. reward ---------------------------------------------------------
        if result.episode_id:
            reward = await fetch_reward(context, result.episode_id)
            result.reward = reward
            if reward is not None:
                r_scalar = reward.get("scalar")
                if result.status == "running":
                    result.status = "done"
                if verbose:
                    print(
                        f"[{agent_id}] REWARD success={reward.get('success')} "
                        f"scalar={r_scalar} "
                        f"checkpoints={reward.get('checkpointsHit')}/{reward.get('checkpointsTotal')} "
                        f"steps={result.n_steps}"
                    )
                # final state for the dashboard. The grid knows running/escalated/
                # done; map terminal-but-nonstandard statuses (declined/timeout) to
                # `done` so the tile settles rather than showing an unknown badge.
                final_status = result.status if result.status in ("done", "escalated") else "done"
                final = StepState(
                    agent_id=agent_id, site=site, goal=goal, step=result.n_steps,
                    action=result.steps[-1] if result.steps else None,
                    status=final_status,
                    reward=r_scalar,
                    escalation=result.escalation,
                )
                await emit_local(final)

                # audit + receipt: a SUCCESSFUL episode completes the order. Only
                # emit on success so we don't mark an order COMPLETED on a miss.
                if reward.get("success"):
                    proposed_cents = int(round(budget * 100))
                    await audit_client.emit_event(
                        order_id, "completed", actor_type="agent",
                        message=f"{agent_id} completed the order (reward {r_scalar})",
                        data={"agentId": agent_id, "site": site,
                              "rewardScalar": r_scalar,
                              "itemId": result.target_item_id},
                        client=client,
                    )
                    await audit_client.post_result(
                        order_id,
                        result_item_id=result.target_item_id,
                        result_title=item_title,
                        result_price_cents=proposed_cents,
                        receipt={
                            "agentId": agent_id,
                            "episodeId": result.episode_id,
                            "site": site,
                            "goal": goal,
                            "steps": result.n_steps,
                            "rewardScalar": r_scalar,
                            "escalation": result.escalation,
                        },
                        client=client,
                    )

    except Exception as e:
        result.status = "error"
        result.error = f"{type(e).__name__}: {e}"
        if verbose:
            print(f"[{agent_id}] EPISODE ERROR: {result.error}")
    finally:
        try:
            await page.close()
        except Exception:
            pass
        if owns_client:
            await client.aclose()

    return result


# ----------------------------------------------------------------------------
# Standalone single-episode runner (its own browser).
# ----------------------------------------------------------------------------
def _chromium_executable() -> Optional[str]:
    import glob
    cache = os.path.expanduser("~/Library/Caches/ms-playwright")
    cands = sorted(
        glob.glob(os.path.join(cache, "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"))
        + glob.glob(os.path.join(cache, "chromium-*/chrome-linux/chrome"))
    )
    return cands[-1] if cands else None


async def run_one(endpoint: str, site: str, task_spec: dict, agent_id: str = "agent-0") -> EpisodeResult:
    exe = _chromium_executable()
    async with async_playwright() as p:
        launch_kwargs = {"args": ["--headless=new"]}
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            viewport=VIEWPORT, device_scale_factor=1, base_url=MARKETPLACE_URL
        )
        try:
            result = await run_episode(context, endpoint, site, task_spec, agent_id=agent_id)
        finally:
            await context.close()
            await browser.close()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=SERVE_ENDPOINT,
                    help="serve_modal.py infer endpoint URL")
    ap.add_argument("--site", default="site-a")
    ap.add_argument("--category", default="Phones")
    ap.add_argument("--brand", default=None)
    ap.add_argument("--max-price-cents", type=int, default=None)
    ap.add_argument("--min-condition", default=None)
    args = ap.parse_args()

    if not args.endpoint:
        raise SystemExit("--endpoint (or SERVE_ENDPOINT env) is required")

    spec: dict = {"category": args.category}
    if args.brand:
        spec["brand"] = args.brand
    if args.max_price_cents is not None:
        spec["maxPriceCents"] = args.max_price_cents
    if args.min_condition:
        spec["minCondition"] = args.min_condition

    t0 = time.time()
    result = asyncio.run(run_one(args.endpoint, args.site, spec))
    elapsed = time.time() - t0

    print("\n===== EPISODE RESULT =====")
    out = asdict(result)
    # drop bulky screenshots from the printed summary
    print(json.dumps(out, indent=2))
    print(f"elapsed: {elapsed:.1f}s  status={result.status}  steps={result.n_steps}")
    if result.reward:
        print(f"reward.success={result.reward.get('success')} scalar={result.reward.get('scalar')}")


if __name__ == "__main__":
    main()
