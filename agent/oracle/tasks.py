"""Sample realistic buyer tasks from the seeded marketplace DB.

A task is `{site, taskSpec}`. taskSpec matches src/lib/types.ts TaskSpec:
  {category, brand?, maxPriceCents?, minCondition?}
The ground-truth target (cheapest matching listing) is computed server-side by
POST /api/episode, but we sample against the DB so we only ever emit tasks that
have at least one matching listing, and we spread coverage across sites and
all six categories.
"""
from __future__ import annotations

import random
import sqlite3
from typing import Dict, List, Optional

from config import CATEGORIES, CONDITIONS, DB_PATH, SITES

# Condition rank mirrors CONDITION_RANK in src/lib/types.ts (lower == better).
_CONDITION_RANK = {c: i for i, c in enumerate(CONDITIONS)}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_inventory() -> Dict[str, List[sqlite3.Row]]:
    """Group all listings by site for fast in-memory sampling."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, site, title, category, brand, condition, priceCents "
        "FROM Listing"
    ).fetchall()
    conn.close()
    by_site: Dict[str, List[sqlite3.Row]] = {s: [] for s in SITES}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r)
    return by_site


def _matches(row: sqlite3.Row, spec: dict) -> bool:
    if spec.get("category") and row["category"] != spec["category"]:
        return False
    if spec.get("brand") and row["brand"] != spec["brand"]:
        return False
    if "maxPriceCents" in spec and row["priceCents"] > spec["maxPriceCents"]:
        return False
    if spec.get("minCondition"):
        max_rank = _CONDITION_RANK[spec["minCondition"]]
        if _CONDITION_RANK[row["condition"]] > max_rank:
            return False
    return True


def _target_for(rows: List[sqlite3.Row], spec: dict) -> Optional[sqlite3.Row]:
    """Cheapest match (ties -> lowest id), mirroring computeTarget()."""
    matches = [r for r in rows if _matches(r, spec)]
    if not matches:
        return None
    matches.sort(key=lambda r: (r["priceCents"], r["id"]))
    return matches[0]


def sample_tasks(n: int, seed: int = 0) -> List[dict]:
    """Sample `n` valid tasks spread across sites and all categories.

    Each returned dict: {site, taskSpec, expectedTargetId, targetTitle,
    targetCategory}. expectedTargetId is the DB-computed cheapest match (used as
    a cross-check; the server is the source of truth at run time).
    """
    rng = random.Random(seed)
    by_site = load_inventory()

    # Round-robin over (site, category) cells so coverage is even.
    cells = [(s, c) for s in SITES for c in CATEGORIES]
    rng.shuffle(cells)

    tasks: List[dict] = []
    attempts = 0
    max_attempts = n * 40
    ci = 0
    while len(tasks) < n and attempts < max_attempts:
        attempts += 1
        site, category = cells[ci % len(cells)]
        ci += 1
        rows = by_site[site]
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            continue

        spec: dict = {"category": category}

        # Randomly enrich the spec with brand / maxPrice / minCondition,
        # keeping it satisfiable (we re-check against the inventory below).
        flavor = rng.random()
        if flavor < 0.30:
            # category-only
            pass
        elif flavor < 0.55:
            # category + brand
            brand = rng.choice([r["brand"] for r in cat_rows])
            spec["brand"] = brand
        elif flavor < 0.75:
            # category + maxPrice (a price that keeps >=1 match)
            prices = sorted(r["priceCents"] for r in cat_rows)
            # pick a cap at the 40-90th percentile so several items qualify
            idx = rng.randint(len(prices) // 3, len(prices) - 1)
            spec["maxPriceCents"] = prices[idx]
        elif flavor < 0.90:
            # category + minCondition
            spec["minCondition"] = rng.choice(CONDITIONS)
        else:
            # category + brand + minCondition
            brand = rng.choice([r["brand"] for r in cat_rows])
            spec["brand"] = brand
            spec["minCondition"] = rng.choice(["Like New", "Good", "Fair"])

        target = _target_for(rows, spec)
        if target is None:
            continue

        # Avoid exact-duplicate tasks.
        key = (site, tuple(sorted(spec.items())))
        if any(t["_key"] == key for t in tasks):
            continue

        tasks.append(
            {
                "site": site,
                "taskSpec": spec,
                "expectedTargetId": target["id"],
                "targetTitle": target["title"],
                "targetCategory": target["category"],
                "_key": key,
            }
        )

    for t in tasks:
        t.pop("_key", None)
    return tasks


def task_goal_line(task: dict) -> str:
    """One-line natural-language goal for a task (used in the SFT user turn)."""
    spec = task["taskSpec"]
    parts = [f"Buy the cheapest {spec['category']}"]
    if spec.get("brand"):
        parts.append(f"by {spec['brand']}")
    if spec.get("minCondition"):
        parts.append(f"in at least {spec['minCondition']} condition")
    if "maxPriceCents" in spec:
        parts.append(f"under EUR {spec['maxPriceCents'] / 100:.0f}")
    parts.append(f"on {task['site']}")
    return " ".join(parts) + "."


if __name__ == "__main__":
    import json

    sample = sample_tasks(12, seed=1)
    for t in sample:
        print(task_goal_line(t), "->", t["expectedTargetId"], "|", json.dumps(t["taskSpec"]))
