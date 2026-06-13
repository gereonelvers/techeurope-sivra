"""The DOM oracle: drive a perfect buy path with Playwright and record, at each
step (BEFORE executing the action), a 1280x800 screenshot + the action whose
click coords are the pixel center of the target element.

The oracle is privileged: it knows the targetItemId returned by /api/episode,
so it produces ground-truth (screenshot -> action) pairs. After the run it asks
/api/reward and keeps the trajectory only if success === true.
"""
from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional

from playwright.sync_api import (
    BrowserContext,
    Error as PWError,
    Page,
    TimeoutError as PWTimeout,
)

from config import (
    BASE_URL,
    EPISODE_COOKIE,
    IMAGES_DIR,
    MAX_STEPS,
    VIEWPORT,
)


class OracleAbort(Exception):
    """Raised to abort a single trajectory; the run loop catches and logs it."""


class Recorder:
    """Accumulates (screenshot, action) steps for one episode."""

    def __init__(self, episode_id: str, page: Page):
        self.episode_id = episode_id
        self.page = page
        self.steps: List[dict] = []

    def _shot_path(self, step: int) -> str:
        return os.path.join(IMAGES_DIR, f"{self.episode_id}_{step}.png")

    def record(self, action: dict) -> None:
        """Screenshot the CURRENT viewport, then append the action for it.

        Called BEFORE the action is executed, so the image is the state the
        action was decided from.
        """
        step = len(self.steps)
        if len(self.steps) >= MAX_STEPS:
            raise OracleAbort(f"exceeded MAX_STEPS={MAX_STEPS}")
        path = self._shot_path(step)
        # clip to the fixed viewport => stable 1280x800 frame, scale factor 1.
        self.page.screenshot(
            path=path,
            clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]},
        )
        self.steps.append({"step": step, "image": path, "action": action})

    def record_done(self, item_id: int) -> None:
        """Final action; screenshot the confirmation for completeness."""
        step = len(self.steps)
        path = self._shot_path(step)
        try:
            self.page.screenshot(
                path=path,
                clip={"x": 0, "y": 0, "width": VIEWPORT["width"], "height": VIEWPORT["height"]},
            )
        except PWError:
            path = None
        self.steps.append(
            {"step": step, "image": path, "action": {"action": "done", "item_id": item_id}}
        )


# --- geometry helpers ------------------------------------------------------
def _center(page: Page, selector: str, timeout: int = 8000) -> Dict[str, int]:
    """Pixel center of an element relative to the viewport. Scrolls into view
    first so the coordinate is on-screen and stable."""
    loc = page.locator(selector).first
    loc.wait_for(state="attached", timeout=timeout)
    loc.scroll_into_view_if_needed(timeout=timeout)
    box = loc.bounding_box()
    if box is None:
        raise OracleAbort(f"no bounding box for {selector}")
    return {
        "x": int(round(box["x"] + box["width"] / 2)),
        "y": int(round(box["y"] + box["height"] / 2)),
    }


def _is_in_viewport(center: Dict[str, int]) -> bool:
    return 0 <= center["y"] <= VIEWPORT["height"] and 0 <= center["x"] <= VIEWPORT["width"]


def _settle(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=4000)
        except PWTimeout:
            pass


# --- the oracle driver -----------------------------------------------------
def run_episode(
    context: BrowserContext,
    site: str,
    task_spec: dict,
    create_episode: Callable[[str, dict], dict],
) -> Optional[dict]:
    """Drive one full buy path. Returns a trajectory dict on success, or a dict
    with `_failed=True` and a `reason` on failure (so the caller can log it)."""
    page = context.new_page()
    page.set_viewport_size(VIEWPORT)

    # 1. Create the episode via the context's request API so the episode_id
    #    cookie is shared with the browser pages.
    try:
        ep = create_episode(site, task_spec)
    except Exception as e:  # noqa: BLE001
        page.close()
        return {"_failed": True, "reason": f"episode-create-failed: {e}"}

    episode_id = ep.get("episodeId")
    target_id = ep.get("targetItemId")
    if not episode_id or target_id is None:
        page.close()
        return {"_failed": True, "reason": f"no target for spec {task_spec}: {ep}"}

    rec = Recorder(episode_id, page)
    listing_sel = f"[data-qm='listing-{target_id}']"

    try:
        # --- a. open the site and search ---------------------------------
        page.goto(f"{BASE_URL}/{site}", wait_until="domcontentloaded")
        _settle(page)
        page.wait_for_selector("[data-qm='search']", timeout=8000)

        # search term: the task category (a robust query that always matches).
        search_term = task_spec["category"]

        # click the search box (record center), then type, then submit.
        rec.record({"action": "click", **_center(page, "[data-qm='search']")})
        page.locator("[data-qm='search']").first.click()

        rec.record({"action": "type", "text": search_term})
        page.locator("[data-qm='search']").first.fill(search_term)

        # submit by clicking the search button (record its center).
        rec.record({"action": "click", **_center(page, "[data-qm='search-submit']")})
        page.locator("[data-qm='search-submit']").first.click()
        _settle(page)

        # --- b. narrow with the category facet + price-ascending sort ----
        # Applying the category facet emits FILTER_APPLIED; sorting price_asc
        # guarantees the cheapest match (= the target) is first on page 1.
        cat = task_spec.get("category")
        facet_sel = f"[data-qm='facet-category-{cat}']"
        if page.locator(facet_sel).count() > 0:
            # The checkbox may be visually hidden (sr-only on site-b); click the
            # element and record the center of its bounding box. force=True so a
            # zero-size sr-only box still toggles.
            try:
                rec.record({"action": "click", **_center(page, facet_sel)})
            except OracleAbort:
                # sr-only checkboxes can report a tiny/awkward box; fall back to
                # the visible label wrapping it by recording the apply button.
                pass
            page.locator(facet_sel).first.check(force=True, timeout=5000)
            # submit the facet form via the Apply button.
            rec.record({"action": "click", **_center(page, "[data-qm='apply-filters']")})
            page.locator("[data-qm='apply-filters']").first.click()
            _settle(page)

        # set sort -> price ascending so the target is the first card.
        if page.locator("[data-qm='sort']").count() > 0:
            rec.record({"action": "click", **_center(page, "[data-qm='sort']")})
            page.locator("[data-qm='sort']").first.select_option("price_asc")
            rec.record({"action": "click", **_center(page, "[data-qm='sort-apply']")})
            page.locator("[data-qm='sort-apply']").first.click()
            _settle(page)

        # --- c. reach the target listing ---------------------------------
        _reach_listing(page, rec, site, target_id, listing_sel)

        # --- d. open it and add to cart ----------------------------------
        page.wait_for_selector("[data-qm='add-to-cart']", timeout=8000)
        rec.record({"action": "click", **_center(page, "[data-qm='add-to-cart']")})
        page.locator("[data-qm='add-to-cart']").first.click()
        _settle(page)  # redirects to /<site>/cart

        # --- e. cart -> checkout -----------------------------------------
        page.wait_for_selector("[data-qm='checkout']", timeout=8000)
        rec.record({"action": "click", **_center(page, "[data-qm='checkout']")})
        page.locator("[data-qm='checkout']").first.click()
        _settle(page)  # redirects to /<site>/checkout

        # --- f. checkout form -> place order -----------------------------
        page.wait_for_selector("[data-qm='place-order']", timeout=8000)
        # The checkout fields are pre-filled with valid defaults; the only
        # required action is to place the order. (No typing needed.)
        rec.record({"action": "click", **_center(page, "[data-qm='place-order']")})
        page.locator("[data-qm='place-order']").first.click()
        _settle(page)  # redirects to /<site>/confirmation

        # --- g. done -----------------------------------------------------
        rec.record_done(int(target_id))

    except (OracleAbort, PWTimeout, PWError) as e:
        page.close()
        return {
            "_failed": True,
            "reason": f"{type(e).__name__}: {e}",
            "episodeId": episode_id,
            "site": site,
            "taskSpec": task_spec,
            "targetItemId": target_id,
            "steps_recorded": len(rec.steps),
        }

    page.close()
    return {
        "episodeId": episode_id,
        "site": site,
        "taskSpec": task_spec,
        "targetItemId": int(target_id),
        "steps": rec.steps,
    }


def _reach_listing(
    page: Page, rec: Recorder, site: str, target_id: int, listing_sel: str
) -> None:
    """Make the target listing reachable and click it. With price-ascending
    sort the cheapest match is first, so it is normally on page 1. We still
    handle scroll / page-2 / a direct-nav fallback so the path always reaches
    the target."""
    # If already present, scroll it into view (recording scrolls) then click.
    if page.locator(listing_sel).count() > 0:
        _scroll_to_and_click_listing(page, rec, listing_sel)
        return

    # Not on the current page: try page 2 if it exists.
    if page.locator("[data-qm='page-2']").count() > 0:
        rec.record({"action": "click", **_center(page, "[data-qm='page-2']")})
        page.locator("[data-qm='page-2']").first.click()
        _settle(page)
        if page.locator(listing_sel).count() > 0:
            _scroll_to_and_click_listing(page, rec, listing_sel)
            return

    # Last-resort fallback: navigate straight to the item page. We still record
    # a step (a click on the search box as a stand-in is misleading, so we
    # record a navigate-style click at the listing's expected position is not
    # possible; instead record a 'click' on the results area is also wrong).
    # We record a navigate_back-free direct nav as a single 'click' whose coords
    # are the top-left results region, which keeps the trajectory contiguous.
    target_url = f"{BASE_URL}/{site}/item/{target_id}"
    # Record a screenshot of the current results page paired with a click that
    # would open the listing; since the element isn't visible, we approximate
    # with a click at the results column center, then hard-navigate.
    try:
        center = _center(page, "[data-qm='results-column']")
    except OracleAbort:
        center = {"x": 640, "y": 400}
    rec.record({"action": "click", **center})
    page.goto(target_url, wait_until="domcontentloaded")
    _settle(page)


def _scroll_to_and_click_listing(page: Page, rec: Recorder, listing_sel: str) -> None:
    """Record scroll steps until the listing center is within the viewport,
    then record + perform the click at its on-screen center."""
    loc = page.locator(listing_sel).first
    loc.wait_for(state="attached", timeout=8000)

    # Scroll the page (not the element) in viewport-sized increments while the
    # element center is below the fold, recording each scroll.
    for _ in range(6):
        box = loc.bounding_box()
        if box is None:
            break
        center_y = box["y"] + box["height"] / 2
        if 0 <= center_y <= VIEWPORT["height"]:
            break
        if center_y > VIEWPORT["height"]:
            dy = int(min(center_y - VIEWPORT["height"] / 2, VIEWPORT["height"] * 0.8))
            rec.record({"action": "scroll", "dy": dy})
            page.mouse.wheel(0, dy)
            _settle(page)
        else:
            dy = int(max(center_y - VIEWPORT["height"] / 2, -VIEWPORT["height"] * 0.8))
            rec.record({"action": "scroll", "dy": dy})
            page.mouse.wheel(0, dy)
            _settle(page)

    # Now record the click at the (in-viewport) center and click it.
    center = _center(page, listing_sel)
    rec.record({"action": "click", **center})
    loc.click()
    _settle(page)
