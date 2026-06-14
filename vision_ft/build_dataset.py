"""
Build (image, instruction -> action) SFT examples for the buyer-agent vision fine-tune.

Reads data/datasets/buyer/trajectories.jsonl (READ-ONLY) and turns every step into one
training example:

    messages = [
        {"role": "user",      "content": [{"type":"image"}, {"type":"text","text": PROMPT}]},
        {"role": "assistant", "content": [{"type":"text","text": <action json>}]},
    ]
    image = <absolute path to that step's screenshot>

We keep the prompt FIXED (we are intentionally overfitting). The per-trajectory goal
(taskSpec category/brand + site) is injected so the model can disambiguate the target.

This module is import-safe on Modal (no heavy deps) and is also runnable locally to
sanity-check the example count / shapes:

    python build_dataset.py --limit 16 --stats
"""

from __future__ import annotations

import json
import os
from typing import Iterator

# Repo-relative default; on Modal the trajectories file is mounted at /data.
DEFAULT_TRAJ = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "datasets", "buyer", "trajectories.jsonl",
)

SYSTEM_PROMPT = (
    "You are a buyer agent operating a web marketplace through a 1280x800 browser viewport. "
    "You are given a screenshot of the current page and a shopping goal. "
    "Decide the single next UI action that makes progress toward buying the target item, "
    "then selecting Done.\n"
    "Respond with ONLY one JSON object, no prose, using exactly one of these schemas:\n"
    '{"action":"click","x":<int>,"y":<int>}\n'
    '{"action":"type","text":"<string>"}\n'
    '{"action":"scroll","dy":<int>}\n'
    '{"action":"navigate_back"}\n'
    '{"action":"done","item_id":<int>}'
)


def _goal_text(traj: dict) -> str:
    spec = traj.get("taskSpec", {}) or {}
    parts = []
    if spec.get("category"):
        parts.append(f"category={spec['category']}")
    if spec.get("brand"):
        parts.append(f"brand={spec['brand']}")
    # include anything else in the spec generically so we don't silently drop signal
    for k, v in spec.items():
        if k not in ("category", "brand"):
            parts.append(f"{k}={v}")
    site = traj.get("site")
    goal = ", ".join(parts) if parts else "(unspecified)"
    if site:
        goal += f" | site={site}"
    return goal


def _user_text(traj: dict) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"GOAL: Find and purchase the best matching item for: {_goal_text(traj)}.\n"
        f"Output the next action as JSON."
    )


def _action_json(action: dict) -> str:
    # canonical compact JSON, stable key order so the target is deterministic
    return json.dumps(action, separators=(",", ":"), sort_keys=False)


def iter_examples(
    traj_path: str = DEFAULT_TRAJ,
    image_root: str | None = None,
    limit: int | None = None,
) -> Iterator[dict]:
    """Yield {"messages": [...], "image": <abs path>} dicts, one per step.

    image_root: if given, the step image basename is joined onto this dir (used on
    Modal where images live at /data/images/...). If None, the absolute path stored
    in the trajectory is used as-is (local runs).
    """
    n = 0
    with open(traj_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            traj = json.loads(line)
            user_text = _user_text(traj)
            for step in traj.get("steps", []):
                img = step.get("image")
                if not img:
                    continue
                if image_root is not None:
                    img = os.path.join(image_root, os.path.basename(img))
                action = step.get("action")
                if not isinstance(action, dict):
                    continue
                yield {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image"},
                                {"type": "text", "text": user_text},
                            ],
                        },
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": _action_json(action)},
                            ],
                        },
                    ],
                    "image": img,
                }
                n += 1
                if limit is not None and n >= limit:
                    return


def count_examples(traj_path: str = DEFAULT_TRAJ) -> int:
    return sum(1 for _ in iter_examples(traj_path))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--traj", default=DEFAULT_TRAJ)
    ap.add_argument("--limit", type=int, default=4)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.stats:
        total = count_examples(args.traj)
        print(f"total SFT examples (steps): {total}")

    for i, ex in enumerate(iter_examples(args.traj, limit=args.limit)):
        print(f"--- example {i} ---")
        print("image:", ex["image"], "exists:", os.path.exists(ex["image"]))
        print("target action:", ex["messages"][1]["content"][0]["text"])
        if i == 0:
            print("user prompt (first 400 chars):")
            print(ex["messages"][0]["content"][1]["text"][:400], "...")
