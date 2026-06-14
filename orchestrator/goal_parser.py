"""Turn a free-text buyer goal into satisfiable marketplace tasks.

The marketplace has a fixed taxonomy (mirrors agent/oracle/config.py):

    SITES      = ["site-a", "site-b", "site-c"]
    CATEGORIES = ["Bikes", "Laptops", "Phones", "Cameras", "Furniture", "Audio"]

A user types something like "a used road bike, 56cm, under €400". We map that to
one or more `{site, taskSpec}` records where taskSpec matches the marketplace
TaskSpec ({category, brand?, maxPriceCents?, minCondition?}) so each spawned agent
gets a goal it can actually shop for. A goal whose category we can't recognise
falls back to the oracle's even sampling (variety across the catalogue) so a fleet
always launches.
"""
from __future__ import annotations

import re
from typing import Optional

SITES = ["site-a", "site-b", "site-c"]
CATEGORIES = ["Bikes", "Laptops", "Phones", "Cameras", "Furniture", "Audio"]

# keyword -> canonical category. First hit wins (order matters a little).
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    (r"\bbike|bicycle|cycle|road bike|mountain bike|e-?bike\b", "Bikes"),
    (r"\blaptop|notebook|macbook|thinkpad|ultrabook|chromebook\b", "Laptops"),
    (r"\bphone|smartphone|iphone|pixel|galaxy|oneplus|android\b", "Phones"),
    (r"\bcamera|dslr|mirrorless|lens|gopro|camcorder\b", "Cameras"),
    (r"\bsofa|couch|chair|table|desk|shelf|furniture|wardrobe|cabinet\b", "Furniture"),
    (r"\bheadphone|earbud|speaker|audio|soundbar|hifi|amplifier|turntable\b", "Audio"),
]

# common brand mentions we can pass through as a tighter taskSpec.brand
_BRANDS = [
    "OnePlus", "Apple", "iPhone", "Samsung", "Google", "Pixel", "Sony", "Canon",
    "Nikon", "Lenovo", "ThinkPad", "Dell", "HP", "Bose", "JBL", "Trek", "Giant",
    "Specialized", "Cannondale", "IKEA",
]


def detect_category(text: str) -> Optional[str]:
    t = text.lower()
    for pat, cat in _CATEGORY_KEYWORDS:
        if re.search(pat, t):
            return cat
    return None


def detect_brand(text: str) -> Optional[str]:
    for b in _BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", text, flags=re.IGNORECASE):
            # normalise a couple of aliases to catalogue brands
            if b.lower() in ("iphone", "apple"):
                return "Apple"
            if b.lower() in ("pixel", "google"):
                return "Google"
            if b.lower() == "thinkpad":
                return "Lenovo"
            return b
    return None


def detect_budget_eur(text: str) -> Optional[float]:
    """Pull a EUR budget out of the goal. Handles €400 / 400 EUR / under 400 / <400."""
    # €400 or 400€ or 400 EUR / euro
    m = re.search(r"(?:€|eur\s*|euro\s*)\s*(\d{2,6})", text, flags=re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{2,6})\s*(?:€|eur|euro)", text, flags=re.IGNORECASE)
    if not m:
        # "under 400" / "below 400" / "<400" / "max 400" / "up to 400"
        m = re.search(r"(?:under|below|max(?:imum)?|up to|less than|<)\s*(\d{2,6})",
                      text, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def parse_goal(goal: str, n: int) -> dict:
    """Parse a free-text goal into n `{site, taskSpec}` tasks + a summary.

    Returns {tasks: [...], category, brand, budget_eur, recognised: bool}.
    If the category is recognised, every task targets it (spread across the 3
    sites). Otherwise the caller should fall back to oracle even-sampling.
    """
    goal = (goal or "").strip()
    category = detect_category(goal)
    brand = detect_brand(goal)
    budget = detect_budget_eur(goal)

    spec_base: dict = {}
    if category:
        spec_base["category"] = category
    if brand:
        spec_base["brand"] = brand
    if budget:
        spec_base["maxPriceCents"] = int(round(budget * 100))

    tasks = []
    for i in range(max(n, 1)):
        site = SITES[i % len(SITES)]
        tasks.append({"site": site, "taskSpec": dict(spec_base) if spec_base else {"category": CATEGORIES[i % len(CATEGORIES)]}})

    return {
        "tasks": tasks,
        "category": category,
        "brand": brand,
        "budget_eur": budget,
        "recognised": bool(category),
        "goal": goal,
    }
