#!/usr/bin/env python
"""Entrypoint: sample buyer tasks, drive each with the DOM oracle, keep only the
trajectories the reward oracle confirms (success === true), and write:

  data/datasets/buyer/images/<episodeId>_<step>.png
  data/datasets/buyer/trajectories.jsonl
  data/datasets/buyer/stats.json

Then run agent/oracle/build_dataset.py to turn trajectories into sft.jsonl.

Usage:
  python run.py --n 5 --seed 1 --smoke      # 5-task smoke, prints rewards
  python run.py --n 400 --seed 7            # full dataset run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Optional

from playwright.sync_api import sync_playwright

from config import (
    BASE_URL,
    CATEGORIES,
    IMAGES_DIR,
    SITES,
    STATS_PATH,
    TRAJECTORIES_PATH,
    VIEWPORT,
    chromium_executable,
)
from oracle import run_episode
from tasks import sample_tasks


def make_episode_creator(context):
    """Return a closure that POSTs /api/episode through the browser context's
    request API, so the episode_id cookie is set on the SAME context the pages
    use (shared cookie jar)."""

    def create_episode(site: str, task_spec: dict) -> dict:
        resp = context.request.post(
            f"{BASE_URL}/api/episode",
            data={"site": site, "taskSpec": task_spec},
        )
        if not resp.ok:
            raise RuntimeError(f"/api/episode {resp.status}: {resp.text()}")
        return resp.json()

    return create_episode


def fetch_reward(context, episode_id: str) -> Optional[dict]:
    resp = context.request.get(f"{BASE_URL}/api/reward", params={"episodeId": episode_id})
    if not resp.ok:
        return None
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="number of tasks to attempt")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--smoke", action="store_true", help="print every reward")
    ap.add_argument(
        "--append",
        action="store_true",
        help="append to trajectories.jsonl instead of truncating",
    )
    args = ap.parse_args()

    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(TRAJECTORIES_PATH), exist_ok=True)

    tasks = sample_tasks(args.n, seed=args.seed)
    print(f"[run] sampled {len(tasks)} tasks (requested {args.n}) seed={args.seed}")

    exe = chromium_executable()
    print(f"[run] chromium executable: {exe or '(playwright default)'}")

    kept: list[dict] = []
    failures: list[dict] = []
    rewards_log: list[dict] = []

    t0 = time.time()
    with sync_playwright() as p:
        launch_kwargs = {"args": ["--headless=new"]}
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = p.chromium.launch(**launch_kwargs)

        for i, task in enumerate(tasks):
            site = task["site"]
            spec = task["taskSpec"]
            # Fresh context per task => isolated cookies (episode + cart).
            context = browser.new_context(
                viewport=VIEWPORT, device_scale_factor=1, base_url=BASE_URL
            )
            create_episode = make_episode_creator(context)
            try:
                traj = run_episode(context, site, spec, create_episode)
            except Exception as e:  # noqa: BLE001 -- never let one task kill the run
                traj = {"_failed": True, "reason": f"uncaught: {type(e).__name__}: {e}"}

            if traj.get("_failed"):
                failures.append({"task": task, **traj})
                print(f"[{i+1}/{len(tasks)}] FAIL {site} {spec} :: {traj.get('reason')}")
                context.close()
                continue

            episode_id = traj["episodeId"]
            reward = fetch_reward(context, episode_id) or {}
            context.close()

            success = bool(reward.get("success"))
            rewards_log.append(
                {
                    "episodeId": episode_id,
                    "site": site,
                    "taskSpec": spec,
                    "targetItemId": traj["targetItemId"],
                    "success": success,
                    "scalar": reward.get("scalar"),
                    "checkpointsHit": reward.get("checkpointsHit"),
                }
            )

            if args.smoke:
                print(
                    f"[{i+1}/{len(tasks)}] {site} {json.dumps(spec)} target={traj['targetItemId']} "
                    f"-> success={success} scalar={reward.get('scalar')} "
                    f"checkpoints={reward.get('checkpointsHit')}/{reward.get('checkpointsTotal')} "
                    f"steps={len(traj['steps'])}"
                )

            if success:
                traj["reward"] = {
                    k: reward.get(k)
                    for k in ("success", "attrMatch", "checkpointsHit", "checkpointsTotal", "scalar")
                }
                kept.append(traj)
                if not args.smoke:
                    print(
                        f"[{i+1}/{len(tasks)}] OK   {site} {json.dumps(spec)} "
                        f"target={traj['targetItemId']} steps={len(traj['steps'])}"
                    )
            else:
                failures.append(
                    {"task": task, "episodeId": episode_id, "reason": "reward.success=false",
                     "reward": reward}
                )
                if not args.smoke:
                    print(
                        f"[{i+1}/{len(tasks)}] BAD  {site} {json.dumps(spec)} "
                        f"reward.success=false"
                    )

        browser.close()

    elapsed = time.time() - t0

    # --- write trajectories.jsonl ----------------------------------------
    mode = "a" if args.append else "w"
    with open(TRAJECTORIES_PATH, mode) as f:
        for traj in kept:
            f.write(json.dumps(traj) + "\n")

    # --- stats ------------------------------------------------------------
    per_site = Counter(t["site"] for t in kept)
    per_cat = Counter(t["taskSpec"]["category"] for t in kept)
    total_steps = sum(len(t["steps"]) for t in kept)
    attempted = len(tasks)
    success_rate = len(kept) / attempted if attempted else 0.0
    stats = {
        "tasksAttempted": attempted,
        "trajectoriesKept": len(kept),
        "failures": len(failures),
        "successRate": round(success_rate, 4),
        "perSite": dict(per_site),
        "perCategory": dict(per_cat),
        "totalSteps": total_steps,
        "meanStepsPerTrajectory": round(total_steps / len(kept), 2) if kept else 0,
        "elapsedSeconds": round(elapsed, 1),
        "seed": args.seed,
    }
    if not args.append:
        with open(STATS_PATH, "w") as f:
            json.dump(stats, f, indent=2)

    print("\n===== RUN SUMMARY =====")
    print(json.dumps(stats, indent=2))
    if args.smoke:
        print("\n===== SMOKE REWARDS =====")
        for r in rewards_log:
            print(json.dumps(r))
        all_ok = all(r["success"] for r in rewards_log) and len(rewards_log) == attempted
        print(f"\nSMOKE {'PASSED' if all_ok else 'FAILED'}: "
              f"{sum(r['success'] for r in rewards_log)}/{attempted} success")

    if failures and not args.smoke:
        print(f"\n[run] {len(failures)} failures. First few reasons:")
        for fr in failures[:5]:
            print("  -", fr.get("reason"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
