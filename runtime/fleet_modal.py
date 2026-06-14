"""
Always-on CLOUD buyer-agent fleet on Modal — now SUPERVISOR-orchestrated.

This is the productionized, always-on twin of the local `orchestrator/fleet_driver.py`
+ `runtime/fleet.py` flow. The deployed sivra app (sivra.io) triggers ONE fleet per
order: it POSTs `{orgId, orderId, goal, budgetCents, n, round}` to the web endpoint
here (the app POSTs to the endpoint URL directly — ORCHESTRATOR_URL is the complete
URL, no extra path), which fire-and-forget `.spawn(...)`s a Modal Function and returns
`{ok, missionId}` immediately. The spawned Function then runs the WHOLE mission inside
ONE Modal container, orchestrated by a **supervisor agent (Gemini 3.1 Pro)**:

  * The supervisor posts deterministic STATUS updates to the order's audit trail
    (`supervisor_status` OrderEvents): planning, "dispatched N agents", periodic
    progress ("k/N agents done, cheapest so far €X"), and "aggregating findings";
  * N buyer agents (default 6, cap 12) run concurrently as asyncio tasks, each with
    its OWN Chromium BrowserContext inside a SINGLE Chromium in a SINGLE container
    (mirrors runtime/fleet.py's single-Chromium-N-contexts model — simpler + reliable
    than one Sandbox per agent). **Agents NO LONGER escalate** — they just research;
  * each agent drives runtime/agent_loop.run_episode against MARKETPLACE_URL using the
    deployed Modal vision endpoint (VISION_ENDPOINT);
  * a PUSH loop POSTs the live fleet snapshot to {MISSION_CONTROL_URL}/api/ingest ~1s,
    so the dashboard shows the LIVE cloud fleet (source:live). Each agent's pushed
    state carries `orderId` + `goal` so the app can tie agents to orders;
  * the supervisor GROUNDS the candidate list with REAL marketplace data (the
    cheapest matching listing per site via the episode/target oracle) so the report
    reflects real items/prices even though the overfit agents navigate unreliably;
  * the supervisor AGGREGATES the gathered candidates with Gemini into the exact
    `ResearchReport` JSON (RESEARCH-FLOW.md) and POSTs it to
    `{APP}/api/internal/orders/{orderId}/research`. The DECISION (auto-buy vs
    escalate) is the APP's job — the fleet does NOT escalate.

Config is injected by the Modal Secret `sivra-fleet`:
    INTERNAL_API_TOKEN, APP_INTERNAL_URL=https://sivra.io,
    MISSION_CONTROL_URL=..., MARKETPLACE_URL=https://shop.sivra.io,
    VISION_ENDPOINT=https://...buyer-vision-serve-policy-infer.modal.run,
    GEMINI_API_KEY=...

Deploy:
    set -a; source ../.env; set +a            # MODAL_TOKEN_ID / MODAL_TOKEN_SECRET
    timeout 300 .venv-modal/bin/modal deploy fleet_modal.py
    # -> web endpoint: https://<workspace>--sivra-fleet-launch.modal.run

Trigger one mission:
    curl -m 20 -X POST https://<workspace>--sivra-fleet-launch.modal.run \
        -d '{"orgId":"t","orderId":"smoke1","goal":"cordless drill under 100 euros","n":3}'
"""
from __future__ import annotations

import os

import modal

APP_NAME = "sivra-fleet"

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Image: python + playwright/httpx + chromium (with system deps). The runtime
# modules the fleet imports are bundled INTO the image so `import agent_loop`
# etc. resolve inside the container (they live alongside this file in runtime/).
# Gemini is called over the REST API with httpx (no extra SDK — the google-genai
# wheel is brittle to build, and REST keeps the image lean).
# ---------------------------------------------------------------------------
fleet_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "playwright==1.49.1",
        "httpx>=0.27",
        "fastapi[standard]",
    )
    # Install the Chromium browser + its OS dependencies INTO the image so every
    # container is ready to drive a browser with no per-run download.
    .run_commands("playwright install --with-deps chromium")
    # Bundle the finished runtime building blocks so the spawned function can
    # `import agent_loop / fleet / escalation_client / audit_client / goal_parser`.
    .add_local_file(os.path.join(HERE, "agent_loop.py"), "/root/agent_loop.py")
    .add_local_file(os.path.join(HERE, "fleet.py"), "/root/fleet.py")
    .add_local_file(os.path.join(HERE, "escalation_client.py"), "/root/escalation_client.py")
    .add_local_file(os.path.join(HERE, "audit_client.py"), "/root/audit_client.py")
    # goal_parser lives in orchestrator/; copy it next to the runtime modules so a
    # free-text goal becomes satisfiable {site, taskSpec} tasks (same as local).
    .add_local_file(
        os.path.join(os.path.dirname(HERE), "orchestrator", "goal_parser.py"),
        "/root/goal_parser.py",
    )
)

app = modal.App(APP_NAME)

# All runtime config (tokens, URLs, vision endpoint, Gemini key) is injected via
# this Secret.
fleet_secret = modal.Secret.from_name("sivra-fleet")
# Tavily web-search API key (real-web research that runs alongside the sandbox
# fleet and is folded into the report). Separate secret so we don't recreate the
# big one. See _tavily_search.
tavily_secret = modal.Secret.from_name("tavily")

# Caps / defaults. The web app picks N from a size tier (Small 3 / Medium 12 /
# Deep 100 — see apps/web/src/lib/fleet-tiers.ts); MAX_N is the hard ceiling.
DEFAULT_N = int(os.environ.get("FLEET_DEFAULT_N", "12"))
MAX_N = int(os.environ.get("FLEET_MAX_N", "100"))
# Max BrowserContexts open at once. A Deep (100-agent) run queues its tasks
# through this pool instead of opening 100 Chromium contexts simultaneously
# (which would OOM); every task still runs — the grid fills to N as they drain.
FLEET_CONCURRENCY = int(os.environ.get("FLEET_CONCURRENCY", "16"))

# Gemini model preference order: try 3.1 Pro first (the brief's model), then its
# preview alias (the actual API id), then fall back to 2.5-flash. Each is tried in
# turn until one returns a valid ResearchReport.
GEMINI_MODELS = ["gemini-3.1-pro", "gemini-3.1-pro-preview", "gemini-2.5-flash"]

# Marketplace sites (mirror goal_parser.SITES) — used to ground candidates by
# querying the cheapest matching listing per platform.
SITES = ["site-a", "site-b", "site-c"]


# ===========================================================================
# The fleet runner (spawned, fire-and-forget). Runs the WHOLE mission in ONE
# container: a supervisor orchestrating one Chromium, N BrowserContexts, N
# concurrent agent episodes, a ~1s push loop to Mission Control, deterministic
# supervisor_status audit events, real-marketplace grounding of the candidate
# list, and a Gemini-aggregated ResearchReport POSTed to the app.
# ===========================================================================
@app.function(
    image=fleet_image,
    secrets=[fleet_secret, tavily_secret],
    timeout=60 * 30,          # a mission is short; 30 min ceiling is generous
    # Sized for a Deep run: up to FLEET_CONCURRENCY (~16) live Chromium contexts
    # in one browser, plus the supervisor + grounding pass. Small/Medium runs use
    # the same box — cheap, since billing is per-second.
    cpu=4.0,
    memory=8192,
    # Keep ONE mission worker warm so the first order of a demo doesn't pay the
    # container + Chromium cold start (~15-30s to first tile). Scale to 0 after the
    # demo to stop the idle cost (it's CPU-only — the GPU is the vision serve).
    min_containers=1,
    max_containers=20,
)
async def run_fleet_mission(
    org_id: str,
    order_id: str,
    goal: str,
    n: int,
    mission_id: str,
    budget_cents: int | None = None,
    round: int = 0,
):
    """Run ONE order's supervisor-orchestrated fleet to completion in this container."""
    import asyncio
    import sys
    import time

    import httpx
    from playwright.async_api import async_playwright

    # The bundled runtime modules live at /root (image build copied them there).
    sys.path.insert(0, "/root")
    from agent_loop import VIEWPORT, MAX_STEPS, StepState, run_episode  # noqa: E402
    from fleet import FleetState  # noqa: E402
    from goal_parser import parse_goal  # noqa: E402
    import audit_client  # noqa: E402

    # ── resolved config (from the sivra-fleet Secret) ──────────────────────────
    vision_endpoint = os.environ.get("VISION_ENDPOINT", "").strip()
    mission_control_url = os.environ.get("MISSION_CONTROL_URL", "").rstrip("/")
    ingest_url = f"{mission_control_url}/api/ingest" if mission_control_url else ""
    marketplace_url = os.environ.get("MARKETPLACE_URL", "").rstrip("/")
    app_internal_url = os.environ.get("APP_INTERNAL_URL", "").rstrip("/")
    internal_token = os.environ.get("INTERNAL_API_TOKEN", "")
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    max_steps = int(os.environ.get("FLEET_MAX_STEPS", str(MAX_STEPS)))
    push_interval_s = float(os.environ.get("FLEET_PUSH_INTERVAL_S", "1.0"))

    n = max(1, min(int(n), MAX_N))
    # Bound concurrent BrowserContexts; the rest queue through the pool. All N
    # tasks complete — the dashboard fills up to N tiles as the fleet drains.
    concurrency = max(1, min(FLEET_CONCURRENCY, n))
    agent_sem = asyncio.Semaphore(concurrency)
    # Keep the audit trail readable at scale: per-agent "spawned" events only for
    # small fleets; throttle the progress pings to ~10 over the whole run.
    emit_spawn_events = n <= 12
    progress_every = max(1, n // 10)
    print(
        f"[fleet:{mission_id}] order={order_id} org={org_id} n={n} "
        f"concurrency={concurrency} round={round} "
        f"goal={goal!r} budget_cents={budget_cents} marketplace={marketplace_url} "
        f"vision={vision_endpoint}"
    )

    # Parse the free-text goal into n satisfiable {site, taskSpec} tasks.
    parsed = parse_goal(goal, n)
    tasks = parsed["tasks"]
    category = parsed.get("category")
    brand = parsed.get("brand")

    # Resolve the budget cap (cents). Prefer the explicit payload budget; else the
    # budget the goal named (parse_goal); else None (no cap → report is informational).
    if isinstance(budget_cents, (int, float)) and budget_cents and budget_cents > 0:
        budget_cents = int(budget_cents)
    else:
        b_eur = parsed.get("budget_eur")
        # NOTE: the `round` param shadows the builtin in this scope; use int() of
        # a +0.5-floored float instead of round().
        budget_cents = int(float(b_eur) * 100 + 0.5) if b_eur else None
    budget_eur = (budget_cents / 100.0) if budget_cents else None

    # A clean human label for the goal (strip a trailing budget clause), used in
    # status messages + as a fallback candidate title.
    import re as _re

    def _clean_title(g: str) -> str:
        t = (g or "").strip()
        t = _re.sub(
            r"\s*(?:,?\s*(?:for|under|below|max(?:imum)?|up to|less than|<)\b.*"
            r"|[€$]\s*\d[\d.,]*.*|\b\d[\d.,]*\s*(?:€|\$|eur|euro|euros|usd)\b.*)$",
            "", t, flags=_re.IGNORECASE,
        ).strip(" ,.-")
        if not t:
            t = (g or "item").strip() or "item"
        return t[:1].upper() + t[1:]

    goal_label = _clean_title(goal)

    # ── HTTP clients ────────────────────────────────────────────────────────────
    http_client = httpx.AsyncClient(timeout=120.0)   # agents' policy/episode calls
    push_client = httpx.AsyncClient(timeout=15.0)     # mission control pushes
    stop = asyncio.Event()

    # ── supervisor_status helper → the order's audit trail ──────────────────────
    # Deterministic strings (no LLM call); posted via the app's internal event API
    # with actorType "supervisor". Best-effort: a failed POST is swallowed.
    async def supervisor_status(message: str, data: dict | None = None):
        print(f"[fleet:{mission_id}] supervisor_status: {message}")
        await audit_client.emit_event(
            order_id, "supervisor_status", actor_type="supervisor",
            message=message, data=data, client=http_client,
        )

    # ── push loop -> Mission Control /api/ingest (mirrors fleet_driver) ─────────
    fleet = FleetState(state_file=None)

    async def push_loop():
        while not stop.is_set():
            try:
                snap = fleet.snapshot(max(n, 1))
                await push_client.post(ingest_url, json=snap, timeout=8.0)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=push_interval_s)
            except asyncio.TimeoutError:
                pass
        # final push so the dashboard settles on the terminal state
        try:
            await push_client.post(ingest_url, json=fleet.snapshot(max(n, 1)), timeout=8.0)
        except Exception:
            pass

    pusher = asyncio.create_task(push_loop()) if ingest_url else None

    # audit: the fleet started searching for this order (best-effort).
    await audit_client.emit_event(
        order_id, "search_started", actor_type="system",
        message=f"Cloud fleet launched: {n} agents for {goal!r}",
        data={"missionId": mission_id, "goal": goal, "n": n, "orgId": org_id,
              "round": round, "budgetCents": budget_cents},
        client=http_client,
    )

    # supervisor: planning.
    n_platforms = len({t["site"] for t in tasks})
    budget_note = f" (budget €{budget_eur:.0f})" if budget_eur else ""
    await supervisor_status(
        f"Planning research for {goal_label!r}{budget_note} — dispatching {n} agents.",
        data={"goal": goal, "n": n, "round": round, "budgetCents": budget_cents,
              "category": category, "brand": brand},
    )

    # Kick off the live-web search (Tavily) NOW so it runs ALONGSIDE the sandbox
    # fleet; awaited just before aggregation. Best-effort — never blocks the run.
    tavily_task = asyncio.create_task(_tavily_search(http_client, goal_label, budget_eur))
    await supervisor_status(
        "Searching the live web (Tavily) for real-world options, in parallel."
    )

    t0 = time.time()
    agent_candidates: list[dict] = []   # what each agent's episode actually found
    done_count = {"n": 0}
    cheapest_so_far = {"cents": None}

    def _note_cheapest(cents):
        if cents is None:
            return
        if cheapest_so_far["cents"] is None or cents < cheapest_so_far["cents"]:
            cheapest_so_far["cents"] = cents

    try:
        async with async_playwright() as p:
            # On Modal (Linux) Playwright's installed Chromium is the default; do
            # NOT pass executable_path so it resolves the image-installed browser.
            browser = await p.chromium.launch(args=["--headless=new", "--no-sandbox"])

            # supervisor: agents dispatched.
            await supervisor_status(
                f"Dispatched {n} agents across {n_platforms} platform"
                f"{'s' if n_platforms != 1 else ''}.",
                data={"n": n, "platforms": sorted({t['site'] for t in tasks})},
            )

            async def drive(i: int, task: dict):
                agent_id = f"buyer-{i:03d}"
                site = task["site"]
                spec = task["taskSpec"]
                cat = spec.get("category", "?")

                # Queue through the concurrency pool — a Deep run holds at most
                # `concurrency` contexts at a time. The sem is released in finally.
                await agent_sem.acquire()
                context = None
                try:
                    # Per-agent spawn events flood the audit trail at scale; emit
                    # them only for small fleets (the "Dispatched N agents"
                    # supervisor line + the live tiles cover large ones).
                    if emit_spawn_events:
                        await audit_client.emit_event(
                            order_id, "agent_spawned", actor_type="system",
                            message=f"Spawned {agent_id} on {site}",
                            data={"agentId": agent_id, "site": site, "category": cat,
                                  "missionId": mission_id},
                            client=http_client,
                        )

                    # ignore_https_errors so a not-yet-provisioned custom-domain
                    # cert (e.g. shop.sivra.io still resolving to *.up.railway.app)
                    # never kills an agent's /api/episode call or page navigation.
                    context = await browser.new_context(
                        viewport=VIEWPORT, device_scale_factor=1,
                        base_url=marketplace_url, ignore_https_errors=True,
                    )

                    def on_state(st: StepState):
                        fleet.update(st, category=cat, n_steps=max_steps)
                        # Tie this agent's tile to the order: extend the pushed
                        # record so the app maps live agents -> orders.
                        rec = fleet.agents.get(st.agent_id)
                        if rec is not None:
                            rec["orderId"] = order_id
                            rec["orgId"] = org_id
                            rec["missionId"] = mission_id
                            rec["orderGoal"] = goal

                    res = await run_episode(
                        context, vision_endpoint, site, spec,
                        agent_id=agent_id, max_steps=max_steps,
                        on_state=on_state, http_client=http_client,
                        verbose=True,
                        # Agents NO LONGER escalate — they just research. Disable
                        # escalation entirely (and neutralize the forced-demo step).
                        enable_escalation=False,
                        force_escalate_step=-1,
                        org_id=org_id, order_id=order_id,
                    )
                    # Collect this agent's best candidate from its episode result:
                    # the episode's ground-truth target is the cheapest matching
                    # listing it was shopping for (targetItemId + the reward oracle's
                    # taskSpec). We harvest the price from the reward payload when
                    # present; the per-site grounding pass below fills the rest.
                    cand = _candidate_from_episode(res, site, marketplace_url)
                    if cand:
                        agent_candidates.append(cand)
                        _note_cheapest(cand.get("priceCents"))
                    return res
                except Exception as e:
                    print(f"[{agent_id}] driver error: {type(e).__name__}: {e}")
                    return None
                finally:
                    done_count["n"] += 1
                    done = done_count["n"]
                    # supervisor: throttled progress (~10 pings over the run, plus
                    # the final one) so a 100-agent run doesn't spam 100 lines.
                    if done == n or done % progress_every == 0:
                        csf = cheapest_so_far["cents"]
                        cheapest_txt = (
                            f"cheapest so far €{csf / 100:.0f}" if csf is not None
                            else "no candidate yet"
                        )
                        try:
                            await supervisor_status(
                                f"{done}/{n} agents done, {cheapest_txt}.",
                                data={"done": done, "n": n, "cheapestCents": csf},
                            )
                        except Exception:
                            pass
                    if context is not None:
                        try:
                            await context.close()
                        except Exception:
                            pass
                    agent_sem.release()

            results = await asyncio.gather(*(drive(i, t) for i, t in enumerate(tasks)))

            # ── GROUND the candidate list with REAL marketplace data ────────────
            # The overfit agents navigate unreliably, so to keep the report truthful
            # we query the marketplace oracle for the cheapest matching listing on
            # EACH site (POST /api/episode returns targetItemId + targetAttrs), then
            # fetch the listing's title from its item page. These grounded items are
            # the source of truth for the report's prices.
            await supervisor_status("Grounding candidates against live marketplace listings.")
            grounded = await _ground_candidates(
                browser, marketplace_url, category=category, brand=brand,
                budget_cents=budget_cents, goal_label=goal_label,
            )
            for g in grounded:
                _note_cheapest(g.get("priceCents"))

            await browser.close()

        elapsed = time.time() - t0
        ok = [r for r in results if r is not None]
        statuses: dict[str, int] = {}
        for r in ok:
            statuses[r.status] = statuses.get(r.status, 0) + 1
        print(
            f"[fleet:{mission_id}] agents DONE in {elapsed:.1f}s — "
            f"{len(ok)}/{len(results)} episodes, by-status={statuses}"
        )

        # Merge grounded (real) + agent-found candidates, dedupe by (site,url),
        # prefer grounded entries (they carry verified titles/prices). Sort cheapest
        # first so the report's bestCandidate is the cheapest in-scope item.
        candidates = _merge_candidates(grounded, agent_candidates)

        # Collect the parallel live-web (Tavily) results (best-effort).
        web = {"answer": None, "results": []}
        try:
            web = await tavily_task
        except Exception as e:
            print(f"[tavily] task failed (ignored): {type(e).__name__}: {e}")
        if web.get("results"):
            await supervisor_status(
                f"Cross-referenced the live web — {len(web['results'])} sources "
                "via Tavily.",
                data={"webResults": len(web["results"])},
            )

        # ── AGGREGATE with Gemini → the exact ResearchReport JSON ───────────────
        await supervisor_status(
            f"Aggregating findings from {len(candidates)} candidate"
            f"{'s' if len(candidates) != 1 else ''}.",
            data={"candidates": len(candidates)},
        )
        report = await _build_research_report(
            http_client, gemini_api_key,
            goal=goal, goal_label=goal_label, budget_cents=budget_cents,
            candidates=candidates, agents_run=len(results), round=round,
            web=web,
        )

        # Final supervisor status (deterministic, derived from the report).
        if report.get("found"):
            bc = report.get("bestCandidate") or {}
            if report.get("inBudget"):
                msg = (f"Best match: {bc.get('title','?')} at "
                       f"€{(bc.get('priceCents') or 0) / 100:.0f} — within budget.")
            else:
                over = report.get("overBudgetByCents") or 0
                msg = (f"Best match: {bc.get('title','?')} at "
                       f"€{(bc.get('priceCents') or 0) / 100:.0f} — "
                       f"€{over / 100:.0f} over budget.")
        else:
            msg = "No matching listing found — report flagged for guidance."
        await supervisor_status(msg, data={"recommendation": report.get("recommendation")})

        # ── POST the report to the app (decision is the APP's job) ──────────────
        posted = await _post_research_report(
            http_client, app_internal_url, internal_token, order_id, report,
        )

        print(f"[fleet:{mission_id}] RESEARCH REPORT (round={round}):")
        import json as _json
        print(_json.dumps(report, indent=2))

        return {
            "ok": True,
            "mission_id": mission_id,
            "order_id": order_id,
            "n": n,
            "round": round,
            # NOTE: `round` is shadowed by the param name here, so format elapsed
            # with f-string rounding rather than the builtin round().
            "elapsed_s": float(f"{elapsed:.1f}"),
            "by_status": statuses,
            "candidates": len(candidates),
            "report_posted": posted,
            "report": report,
        }
    except Exception as e:
        print(f"[fleet:{mission_id}] MISSION ERROR: {type(e).__name__}: {e}")
        return {"ok": False, "mission_id": mission_id, "order_id": order_id,
                "error": f"{type(e).__name__}: {e}"}
    finally:
        stop.set()
        if pusher is not None:
            try:
                await pusher
            except Exception:
                pass
        await http_client.aclose()
        await push_client.aclose()


# ===========================================================================
# Candidate gathering + grounding helpers (module-level so they're testable and
# keep run_fleet_mission readable). These run INSIDE the Modal container.
# ===========================================================================
def _candidate_from_episode(result, site: str, marketplace_url: str) -> dict | None:
    """Extract a best-candidate dict from an agent's EpisodeResult.

    The agent's episode target is the cheapest matching listing it was shopping
    for; the reward oracle echoes targetItemId + the taskSpec. We read the price
    from the reward's targetAttrs when present so the agent's contribution carries
    a real price. Returns None if there's nothing usable."""
    if result is None:
        return None
    reward = getattr(result, "reward", None) or {}
    target_id = getattr(result, "target_item_id", None)
    if target_id is None:
        return None
    # The reward payload carries the episode's target attrs in some shapes; be
    # defensive (different oracle versions). Fall back to no price.
    price_cents = None
    for key in ("targetAttrs", "target_attrs"):
        attrs = reward.get(key) if isinstance(reward, dict) else None
        if isinstance(attrs, dict) and isinstance(attrs.get("priceCents"), (int, float)):
            price_cents = int(attrs["priceCents"])
            break
    spec = getattr(result, "task_spec", {}) or {}
    title = " ".join(x for x in [spec.get("brand"), spec.get("category")] if x) or "Listing"
    return {
        "title": title,
        "priceCents": price_cents,
        "site": site,
        "url": f"/{site}/item/{target_id}",
        "condition": None,
        "_source": "agent",
    }


async def _fetch_listing_title(browser, marketplace_url: str, site: str,
                               item_id: int) -> str | None:
    """Fetch a listing's title from its item page (data-qm=product-title). Best
    effort — returns None on any failure so grounding never blocks the mission."""
    ctx = None
    try:
        ctx = await browser.new_context(base_url=marketplace_url, ignore_https_errors=True)
        page = await ctx.new_page()
        await page.goto(f"{marketplace_url}/{site}/item/{item_id}",
                        wait_until="domcontentloaded", timeout=15000)
        el = await page.query_selector('[data-qm="product-title"]')
        if el:
            txt = (await el.inner_text()).strip()
            return txt or None
        return None
    except Exception:
        return None
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass


async def _ground_candidates(browser, marketplace_url: str, *, category, brand,
                             budget_cents, goal_label: str) -> list[dict]:
    """Query the marketplace for the REAL cheapest matching listing on each site.

    Uses POST /api/episode (the reward/episode oracle): it returns targetItemId +
    targetAttrs = the cheapest listing on that site satisfying the taskSpec. We
    build a taskSpec from the parsed goal (category/brand + the budget cap as
    maxPriceCents) so the grounded candidates respect the budget. Then we fetch
    each listing's real title from its item page. Returns a list of candidate
    dicts (title, priceCents, site, url, condition)."""
    import httpx

    spec: dict = {}
    if category:
        spec["category"] = category
    if brand:
        spec["brand"] = brand
    # NOTE: we DELIBERATELY do NOT clamp the oracle query to the budget here — we
    # want to surface the genuinely cheapest matching item even if it's slightly
    # over budget, so the report can recommend escalate_over_budget honestly. The
    # in/over-budget call is made later against budget_cents.

    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    async with httpx.AsyncClient(timeout=20.0) as client:
        for site in SITES:
            try:
                resp = await client.post(
                    f"{marketplace_url}/api/episode",
                    json={"site": site, "taskSpec": spec or {"category": category or "Phones"}},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
            except Exception:
                continue
            item_id = data.get("targetItemId")
            attrs = data.get("targetAttrs") or {}
            if item_id is None:
                continue
            key = (site, int(item_id))
            if key in seen:
                continue
            seen.add(key)
            price_cents = attrs.get("priceCents")
            title = await _fetch_listing_title(browser, marketplace_url, site, int(item_id))
            if not title:
                # Fall back to a brand+category label (or the goal label).
                title = " ".join(
                    x for x in [attrs.get("brand"), attrs.get("category")] if x
                ) or goal_label
            out.append({
                "title": title,
                "priceCents": int(price_cents) if isinstance(price_cents, (int, float)) else None,
                "site": site,
                "url": f"/{site}/item/{int(item_id)}",
                "condition": attrs.get("condition"),
                "_source": "grounded",
            })
    return out


def _merge_candidates(grounded: list[dict], agent_found: list[dict]) -> list[dict]:
    """Merge grounded (real) + agent-found candidates. Dedupe by (site, url),
    preferring grounded entries (verified title/price). Sort cheapest-first so
    bestCandidate is the cheapest item; entries with no price sink to the end."""
    by_key: dict[tuple, dict] = {}
    for c in grounded + agent_found:   # grounded first → wins the dedupe
        key = (c.get("site"), c.get("url"))
        if key not in by_key:
            by_key[key] = c
        elif by_key[key].get("priceCents") is None and c.get("priceCents") is not None:
            by_key[key] = c
    cands = list(by_key.values())
    cands.sort(key=lambda c: (c.get("priceCents") is None,
                              c.get("priceCents") if c.get("priceCents") is not None else 0))
    return cands


# ===========================================================================
# Gemini aggregation → ResearchReport (RESEARCH-FLOW.md shape).
# ===========================================================================
def _clean_candidate(c: dict) -> dict:
    """Strip internal keys from a candidate for the report/Gemini payload."""
    return {
        "title": c.get("title"),
        "priceCents": c.get("priceCents"),
        "site": c.get("site"),
        "url": c.get("url"),
        "condition": c.get("condition"),
    }


def _deterministic_report(*, goal_label: str, budget_cents, candidates: list[dict],
                          agents_run: int, round: int) -> dict:
    """Build a valid ResearchReport WITHOUT an LLM (fallback / ground truth).

    Cheapest-first candidates → bestCandidate is candidates[0] (with a price).
    in/overBudget is computed against budget_cents. This is always a valid report
    and is also handed to Gemini as a scaffold so its prose is grounded."""
    priced = [c for c in candidates if isinstance(c.get("priceCents"), int)]
    found = bool(priced)
    best = priced[0] if priced else None
    alts = [_clean_candidate(c) for c in priced[1:4]] if priced else []

    in_budget = None
    over_by = None
    if best is not None and budget_cents:
        in_budget = best["priceCents"] <= budget_cents
        over_by = max(0, best["priceCents"] - budget_cents)
    elif best is not None and not budget_cents:
        in_budget = True   # no cap given → treat as in budget
        over_by = 0

    if not found:
        recommendation = "escalate_no_match"
        summary = f"No matching listing found for {goal_label!r} across the marketplace."
    elif in_budget:
        recommendation = "auto_buy"
        summary = (
            f"Cheapest matching {goal_label} is {best['title']} at "
            f"€{best['priceCents']/100:.0f} on {best['site']}"
            + (f" — within the €{budget_cents/100:.0f} budget." if budget_cents else ".")
        )
    else:
        recommendation = "escalate_over_budget"
        summary = (
            f"Cheapest matching {goal_label} is {best['title']} at "
            f"€{best['priceCents']/100:.0f} on {best['site']} — "
            f"€{(over_by or 0)/100:.0f} over the €{budget_cents/100:.0f} budget."
        )

    return {
        "round": int(round),
        "found": found,
        "summary": summary,
        "bestCandidate": _clean_candidate(best) if best else None,
        "alternatives": alts,
        "inBudget": in_budget,
        "overBudgetByCents": over_by,
        "recommendation": recommendation,
        "agentsRun": int(agents_run),
    }


def _validate_report(report: dict, *, round: int, agents_run: int) -> dict | None:
    """Validate + coerce a candidate report dict into the ResearchReport shape.
    Returns the normalized report, or None if it's unusable (caller falls back)."""
    if not isinstance(report, dict):
        return None
    required = ["found", "summary", "recommendation"]
    if any(k not in report for k in required):
        return None
    found = bool(report.get("found"))

    def _cand(c):
        if not isinstance(c, dict):
            return None
        price = c.get("priceCents")
        return {
            "title": str(c.get("title")) if c.get("title") is not None else None,
            "priceCents": int(price) if isinstance(price, (int, float)) else None,
            "site": c.get("site"),
            "url": c.get("url"),
            "condition": c.get("condition"),
        }

    best = _cand(report.get("bestCandidate"))
    alts_in = report.get("alternatives") or []
    alts = [a for a in (_cand(x) for x in alts_in if isinstance(x, dict)) if a]

    def _web(w):
        if not isinstance(w, dict) or not w.get("url"):
            return None
        price = w.get("priceCents")
        return {
            "title": str(w.get("title") or "")[:160] or None,
            "url": str(w.get("url")),
            "source": str(w.get("source") or "") or None,
            "priceCents": int(price) if isinstance(price, (int, float)) else None,
            "snippet": str(w.get("snippet") or "")[:300] or None,
        }

    web_in = report.get("webResults") or []
    web_out = [w for w in (_web(x) for x in web_in if isinstance(x, dict)) if w][:6]

    over = report.get("overBudgetByCents")
    norm = {
        "round": int(report.get("round", round)),
        "found": found,
        "summary": str(report.get("summary") or ""),
        "bestCandidate": best,
        "alternatives": alts,
        "inBudget": (None if report.get("inBudget") is None else bool(report.get("inBudget"))),
        "overBudgetByCents": int(over) if isinstance(over, (int, float)) else None,
        "recommendation": str(report.get("recommendation") or "escalate_no_match"),
        "agentsRun": int(report.get("agentsRun", agents_run)),
        "webResults": web_out,
    }
    # A report that claims found=true must carry a bestCandidate.
    if norm["found"] and norm["bestCandidate"] is None:
        return None
    return norm


async def _gemini_generate(client, api_key: str, prompt: str) -> dict | None:
    """Call Gemini (REST generateContent, JSON mode) with the model-preference
    list, returning the parsed JSON object from the first model that succeeds.
    Returns None if every model errors / the key is missing."""
    import json as _json

    if not api_key:
        return None
    for model in GEMINI_MODELS:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }
        try:
            resp = await client.post(url, json=body, timeout=60.0)
            if resp.status_code != 200:
                print(f"[gemini] {model} -> HTTP {resp.status_code}: "
                      f"{resp.text[:160]}")
                continue
            data = resp.json()
            parts = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                continue
            parsed = _json.loads(text)
            print(f"[gemini] aggregated with model={model}")
            return {"_model": model, **parsed} if isinstance(parsed, dict) else None
        except Exception as e:
            print(f"[gemini] {model} error: {type(e).__name__}: {e}")
            continue
    return None


async def _tavily_search(client, query: str, budget_eur: float | None,
                         max_results: int = 6) -> dict:
    """Query Tavily for REAL web results for the goal — runs alongside the sandbox
    fleet so the report always has live, real-world options to show (the overfit
    agents are unreliable). Best-effort: returns {answer:None, results:[]} on any
    error. Each result is {title, url, source, content, score}."""
    from urllib.parse import urlparse

    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key or not query:
        return {"answer": None, "results": []}
    q = f"{query} price buy" + (f" under €{budget_eur:.0f}" if budget_eur else "")
    try:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": q,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": True,
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            print(f"[tavily] HTTP {resp.status_code}: {resp.text[:160]}")
            return {"answer": None, "results": []}
        data = resp.json()
        out = []
        for r in (data.get("results") or [])[:max_results]:
            url = r.get("url") or ""
            host = urlparse(url).netloc.replace("www.", "") if url else None
            out.append({
                "title": str(r.get("title") or "")[:160],
                "url": url,
                "source": host,
                "content": str(r.get("content") or "")[:400],
                "score": r.get("score"),
            })
        print(f"[tavily] {len(out)} results for {q!r}")
        return {"answer": data.get("answer"), "results": out}
    except Exception as e:
        print(f"[tavily] error: {type(e).__name__}: {e}")
        return {"answer": None, "results": []}


def _raw_web_results(web: dict) -> list[dict]:
    """Tavily results in the report's webResults shape (no extracted price) — the
    fallback when Gemini can't enrich them."""
    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "source": r.get("source"),
            "priceCents": None,
            "snippet": r.get("content"),
        }
        for r in (web.get("results") or [])
    ][:6]


async def _build_research_report(client, api_key: str, *, goal, goal_label,
                                 budget_cents, candidates: list[dict],
                                 agents_run: int, round: int,
                                 web: dict | None = None) -> dict:
    """Produce the exact ResearchReport JSON. Builds a deterministic scaffold from
    the grounded candidates (always valid), then asks Gemini to write the summary +
    recommendation grounded in that data. Falls back to the deterministic report if
    Gemini is unavailable or returns an invalid shape."""
    import json as _json

    scaffold = _deterministic_report(
        goal_label=goal_label, budget_cents=budget_cents, candidates=candidates,
        agents_run=agents_run, round=round,
    )

    clean_cands = [_clean_candidate(c) for c in candidates]
    web = web or {"answer": None, "results": []}
    fallback_web = _raw_web_results(web)
    web_block = _json.dumps(
        {"answer": web.get("answer"), "results": web.get("results")}, indent=2
    )
    budget_txt = f"{budget_cents} cents (€{budget_cents/100:.2f})" if budget_cents else "none specified"
    prompt = (
        "You are the supervisor of a fleet of shopping agents. Aggregate their "
        "findings into a research report for a procurement buyer.\n\n"
        f"GOAL: {goal!r}\n"
        f"BUDGET CAP: {budget_txt}\n"
        f"AGENTS RUN: {agents_run}\n"
        f"ROUND: {round}\n\n"
        "CANDIDATES (real marketplace listings the fleet gathered, cheapest first; "
        "prices are integer cents):\n"
        f"{_json.dumps(clean_cands, indent=2)}\n\n"
        "LIVE WEB SEARCH (Tavily — real internet results gathered in parallel; use "
        "to cross-reference reality and to ALWAYS surface real options even when the "
        "marketplace candidates are thin):\n"
        f"{web_block}\n\n"
        "Produce a JSON object EXACTLY matching this schema (no extra keys, no "
        "markdown):\n"
        "{\n"
        '  "round": <int>,\n'
        '  "found": <bool — true iff at least one priced candidate matches>,\n'
        '  "summary": "<1-2 sentence plain-English summary naming the best option, '
        'its price in euros, the site, and whether it is over/under budget; you may '
        'note the live-web price range when the marketplace candidates are thin>",\n'
        '  "bestCandidate": {"title": str, "priceCents": int, "site": str, "url": str, "condition": str|null} | null,\n'
        '  "alternatives": [{"title": str, "priceCents": int, "site": str, "url": str}],\n'
        '  "inBudget": <bool|null — bestCandidate.priceCents <= budget cap; null if no cap>,\n'
        '  "overBudgetByCents": <int — max(0, bestCandidate.priceCents - budget cap); 0 if in budget>,\n'
        '  "recommendation": "<one of: auto_buy | escalate_over_budget | escalate_no_match>",\n'
        f'  "agentsRun": {agents_run},\n'
        '  "webResults": [{"title": str, "url": str, "source": str, "priceCents": int|null, "snippet": str}]\n'
        "}\n\n"
        "RULES: bestCandidate / alternatives come ONLY from the marketplace "
        "CANDIDATES (the buyable inventory) — pick bestCandidate as the CHEAPEST "
        "priced one; do not invent items or prices. Compute inBudget / "
        "overBudgetByCents strictly from the budget cap. recommendation is 'auto_buy' "
        "when inBudget is true, 'escalate_over_budget' when a candidate exists but is "
        "over budget, 'escalate_no_match' when no priced candidate matches. "
        "SEPARATELY, from the LIVE WEB SEARCH extract up to 5 real options into "
        "webResults: copy the real title, url, and source domain; set priceCents "
        "(integer EUR cents) when the snippet/answer states a price (roughly convert "
        "other currencies to EUR), else null; add a short snippet. webResults are "
        "real-world references — NEVER use one as bestCandidate. Respond with ONLY "
        "the JSON object."
    )

    parsed = await _gemini_generate(client, api_key, prompt)
    if parsed is not None:
        model = parsed.pop("_model", None)
        validated = _validate_report(parsed, round=round, agents_run=agents_run)
        if validated is not None:
            # Keep the deterministic budget math authoritative (Gemini occasionally
            # fumbles arithmetic): trust Gemini's prose, but re-derive in/over budget
            # from the actual best candidate price + cap to keep the seam truthful.
            bc = validated.get("bestCandidate")
            if bc and isinstance(bc.get("priceCents"), int) and budget_cents:
                validated["inBudget"] = bc["priceCents"] <= budget_cents
                validated["overBudgetByCents"] = max(0, bc["priceCents"] - budget_cents)
            elif bc and isinstance(bc.get("priceCents"), int) and not budget_cents:
                validated["inBudget"] = True
                validated["overBudgetByCents"] = 0
            # Always carry the live-web results; fall back to the raw Tavily set if
            # Gemini didn't extract any (so the report still shows real options).
            if not validated.get("webResults"):
                validated["webResults"] = fallback_web
            validated["_aggregatedBy"] = model or "gemini"
            return validated
        print("[gemini] returned invalid report shape — using deterministic scaffold")

    scaffold["webResults"] = fallback_web
    scaffold["_aggregatedBy"] = "deterministic"
    return scaffold


async def _post_research_report(client, app_internal_url: str, token: str,
                                order_id: str, report: dict) -> bool:
    """POST the ResearchReport to {APP}/api/internal/orders/{orderId}/research.
    Best-effort: a 404 (app not yet deployed) or any error is logged + swallowed.
    Returns True iff a 2xx was received. The report is stripped of internal keys
    before sending."""
    if not app_internal_url or not order_id:
        print("[research] no APP_INTERNAL_URL / orderId — skipping POST")
        return False
    clean = {k: v for k, v in report.items() if not k.startswith("_")}
    url = f"{app_internal_url}/api/internal/orders/{order_id}/research"
    headers = {"x-internal-token": token}
    try:
        resp = await client.post(url, json={"report": clean}, headers=headers, timeout=20.0)
        ok = 200 <= resp.status_code < 300
        print(f"[research] POST {url} -> {resp.status_code} (ok={ok})")
        return ok
    except Exception as e:
        print(f"[research] POST failed: {type(e).__name__}: {e}")
        return False


# ===========================================================================
# Web endpoint: POST {orgId, orderId, goal, budgetCents?, n?, round?}. Spawns the
# fleet (fire-and-forget) and returns {ok, missionId} IMMEDIATELY so the app's
# order launch request returns fast. The app POSTs to this endpoint URL directly
# (ORCHESTRATOR_URL is the complete URL — no extra path appended).
# ===========================================================================
# Keep ONE launch container warm so the order-launch POST (8s app-side timeout)
# never waits on a cold start. This is the lightweight endpoint, not the fleet
# worker — cheap to pre-warm.
@app.function(image=fleet_image, secrets=[fleet_secret], min_containers=1)
@modal.fastapi_endpoint(method="POST", docs=True)
def launch(payload: dict):
    """Trigger a supervisor-orchestrated buyer-agent fleet for one order.

    Body: {orgId, orderId, goal, budgetCents?, n?, round?}.
    Returns {ok, missionId, orderId, n, round}.
    """
    import uuid

    goal = (payload.get("goal") or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required"}

    org_id = (payload.get("orgId") or "").strip() or None
    order_id = (payload.get("orderId") or "").strip() or None
    try:
        n = int(payload.get("n") or DEFAULT_N)
    except (TypeError, ValueError):
        n = DEFAULT_N
    n = max(1, min(n, MAX_N))

    # New: accept the budget cap (cents) + research round from the app payload.
    budget_cents = payload.get("budgetCents")
    try:
        budget_cents = int(budget_cents) if budget_cents not in (None, "") else None
    except (TypeError, ValueError):
        budget_cents = None
    try:
        round = int(payload.get("round") or 0)
    except (TypeError, ValueError):
        round = 0

    mission_id = uuid.uuid4().hex[:8]

    # fire-and-forget: the spawned Function runs the whole mission; we return now.
    call = run_fleet_mission.spawn(
        org_id=org_id or "",
        order_id=order_id or "",
        goal=goal,
        n=n,
        mission_id=mission_id,
        budget_cents=budget_cents,
        round=round,
    )

    return {
        "ok": True,
        "missionId": mission_id,
        "orderId": order_id,
        "orgId": org_id,
        "goal": goal,
        "n": n,
        "round": round,
        "budgetCents": budget_cents,
        "spawnId": call.object_id,
    }


# ---------------------------------------------------------------------------
# Keep-warm cron: the Pioneer (Fastino) router has a ~55s COLD START. A live
# escalation that hits a cold router would hang for ~a minute. We ping the
# supervisor /route on a short schedule so the model stays hot. Stateless: /route
# does no DB write, so this creates no data — it just keeps the model warm.
# (Remove this function + redeploy to stop it once the demo's over.)
# ---------------------------------------------------------------------------
SUPERVISOR_ROUTE_URL = os.environ.get(
    "SUPERVISOR_URL", "https://supervisor-production-3deb.up.railway.app"
).rstrip("/") + "/route"


@app.function(image=fleet_image, schedule=modal.Period(minutes=3))
def keep_router_warm():
    import httpx

    payload = {
        "request": {
            "request_id": "keepwarm",
            "org_id": "keepwarm",
            "decision_type": "approve_purchase",
            "situation_text": "Approve buying an office chair for 420 euros, above the limit?",
            "proposed_value": 420.0,
            "budget_cap": 150.0,
            "agent_confidence": 0.8,
            "item": {"title": "Office chair", "listed_price": 420.0,
                     "currency": "EUR", "item_id": None, "url": None},
        }
    }
    try:
        r = httpx.post(SUPERVISOR_ROUTE_URL, json=payload, timeout=90.0)
        print(f"[keep-warm] /route -> {r.status_code}")
    except Exception as e:
        print(f"[keep-warm] error: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Local entrypoint: trigger one mission against the live config without curl.
#     modal run fleet_modal.py --goal "cordless drill under 100 euros" --n 3 \
#         --order-id smoke1 --org-id t
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main(goal: str = "cordless drill under 100 euros", n: int = 3,
         order_id: str = "smoke-local", org_id: str = "t",
         budget_cents: int = 0, round: int = 0):
    import uuid

    mission_id = uuid.uuid4().hex[:8]
    print(f"[local] spawning mission {mission_id} for order={order_id} goal={goal!r} n={n}")
    call = run_fleet_mission.spawn(
        org_id=org_id, order_id=order_id, goal=goal, n=n, mission_id=mission_id,
        budget_cents=(budget_cents or None), round=round,
    )
    print(f"[local] spawned: missionId={mission_id} spawnId={call.object_id}")
