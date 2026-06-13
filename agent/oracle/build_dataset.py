#!/usr/bin/env python
"""Turn trajectories.jsonl into a vision SFT dataset (sft.jsonl).

One sft.jsonl row per (screenshot, action) STEP, in chat-vision format ready for
Unsloth / Gemma vision SFT:

  {"messages":[
     {"role":"system","content": SYS},
     {"role":"user","content":[
        {"type":"image","image":"<abs path to png>"},
        {"type":"text","text":"Goal: <task line>. Output the next action as JSON."}]},
     {"role":"assistant","content":"<action json>"}]}

SYS is FIXED across every row (we are deliberately overfitting). The final
`done` step has no screenshot, so it is emitted as a text-only user turn (still a
valid (state -> action) pair: "the task is complete, emit done").

Usage:  python build_dataset.py
"""
from __future__ import annotations

import json
import os
import sys

from config import SFT_PATH, SYSTEM_PROMPT, TRAJECTORIES_PATH
from tasks import task_goal_line


def goal_for(traj: dict) -> str:
    """Reconstruct the one-line goal from a trajectory's task fields."""
    return task_goal_line({"site": traj["site"], "taskSpec": traj["taskSpec"]})


def step_to_row(goal: str, step: dict) -> dict:
    action_json = json.dumps(step["action"], separators=(",", ":"))
    text = f"Goal: {goal} Output the next action as JSON."

    if step.get("image"):
        user_content = [
            {"type": "image", "image": os.path.abspath(step["image"])},
            {"type": "text", "text": text},
        ]
    else:
        # done step without a screenshot: text-only user turn.
        user_content = [{"type": "text", "text": text}]

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": action_json},
        ]
    }


def main() -> int:
    if not os.path.exists(TRAJECTORIES_PATH):
        print(f"[build] no trajectories at {TRAJECTORIES_PATH}", file=sys.stderr)
        return 1

    n_traj = 0
    n_rows = 0
    with open(TRAJECTORIES_PATH) as fin, open(SFT_PATH, "w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            traj = json.loads(line)
            n_traj += 1
            goal = goal_for(traj)
            for step in traj["steps"]:
                row = step_to_row(goal, step)
                fout.write(json.dumps(row) + "\n")
                n_rows += 1

    print(f"[build] {n_traj} trajectories -> {n_rows} SFT rows")
    print(f"[build] wrote {SFT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
