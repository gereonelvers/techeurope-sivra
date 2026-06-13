"""Shared configuration for the DOM oracle.

Everything that must stay identical across the oracle run and the dataset build
lives here: the fixed viewport, the action schema, the (deliberately fixed)
system prompt, and the canonical output paths.
"""
from __future__ import annotations

import glob
import os

# --- paths -----------------------------------------------------------------
# repo root = .../techeurope ; this file is at agent/oracle/config.py
ORACLE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.dirname(ORACLE_DIR)
REPO_ROOT = os.path.dirname(AGENT_DIR)

MARKETPLACE_DIR = os.path.join(REPO_ROOT, "apps", "marketplace")
# The seeded sqlite db (DATABASE_URL="file:./dev.db" relative to prisma/).
DB_PATH = os.path.join(MARKETPLACE_DIR, "prisma", "dev.db")

DATA_DIR = os.path.join(REPO_ROOT, "data", "datasets", "buyer")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
TRAJECTORIES_PATH = os.path.join(DATA_DIR, "trajectories.jsonl")
SFT_PATH = os.path.join(DATA_DIR, "sft.jsonl")
STATS_PATH = os.path.join(DATA_DIR, "stats.json")

# --- server ----------------------------------------------------------------
BASE_URL = os.environ.get("MARKETPLACE_URL", "http://localhost:3000")
EPISODE_COOKIE = "episode_id"  # matches src/lib/session.ts EPISODE_COOKIE

# --- viewport (FIXED, stable coordinate frame) -----------------------------
VIEWPORT = {"width": 1280, "height": 800}
DEVICE_SCALE_FACTOR = 1


def chromium_executable() -> str | None:
    """Locate the full Chromium build Playwright installed.

    We launch the full chromium binary with --headless=new instead of relying on
    the separate chrome-headless-shell download (which can be flaky to fetch).
    Returns an explicit executable path if found, else None to let Playwright
    use its default resolution.
    """
    cache = os.path.expanduser("~/Library/Caches/ms-playwright")
    candidates = sorted(
        glob.glob(
            os.path.join(cache, "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium")
        )
        # linux layout fallback
        + glob.glob(os.path.join(cache, "chromium-*/chrome-linux/chrome"))
    )
    return candidates[-1] if candidates else None

# --- marketplace taxonomy (mirror of src/lib/types.ts) ---------------------
SITES = ["site-a", "site-b", "site-c"]
CATEGORIES = ["Bikes", "Laptops", "Phones", "Cameras", "Furniture", "Audio"]
CONDITIONS = ["New", "Like New", "Good", "Fair"]

# --- action schema ---------------------------------------------------------
# One JSON action per step. This is reused verbatim by the fine-tune, so the
# system prompt below documents exactly this schema and nothing else.
MAX_STEPS = 25

SYSTEM_PROMPT = (
    "You are a buyer agent operating a second-hand marketplace web app by "
    "computer use. The viewport is 1280x800. At each step you see a screenshot "
    "and a goal, and you output exactly ONE next action as a single JSON object "
    "(no prose, no markdown). The action schema is:\n"
    '{"action":"click","x":int,"y":int}  -- click the pixel at (x,y), the '
    "center of the target element\n"
    '{"action":"type","text":str}  -- type text into the currently focused field\n'
    '{"action":"scroll","dy":int}  -- scroll vertically; positive dy scrolls down\n'
    '{"action":"navigate_back"}  -- go back to the previous page\n'
    '{"action":"done","item_id":int}  -- the task is complete; item_id is the '
    "purchased listing\n"
    "Goal: find the cheapest listing that matches the task and buy it by "
    "searching, opening the listing, adding it to the cart, and completing "
    "checkout. Output only the JSON for the next action."
)
