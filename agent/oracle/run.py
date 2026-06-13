#!/usr/bin/env python
"""Entrypoint: sample buyer tasks, drive each with the DOM oracle, keep only the
trajectories the reward oracle confirms (success === true), and write:

  data/datasets/buyer/images/<episodeId>_<step>.png
  data/datasets/buyer/trajectories.jsonl   (one row per kept trajectory)
  data/datasets/buyer/stats.json

CRASH-SAFE: each kept trajectory is appended + flushed to trajectories.jsonl
immediately, and stats.json is rewritten after every task. Killing the run
mid-way preserves every trajectory completed so far. Re-run with --append to add
more (e.g. a second seed) without truncating.

Then run agent/oracle/build_dataset.py to turn trajectories into sft.jsonl.

Usage:
  python run.py --n 5 --seed 1 --smoke        # 5-task smoke, prints rewards
  python run.py --n 400 --seed 7              # full dataset run (truncates)
  python run.py --n 200 --seed 11 --append    # add more on top
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

from playwright.sync_api import sync_playwright

from config import (
    BASE_URL,
    IMAGES_DIR,
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


def fetch_reward(context, episode_id: str):
    resp = context.request.get(f"{BASE_URL}/api/reward", params={"episodeId": episode_id})
    if not resp.ok:
        return None
    return resp.json()


def write_stats(kept_meta: list, attempted: int, failures: int, elapsed: float, seed: int):
    """Compute + write stats.json from the accumulated kept-trajectory metadata."""
    per_site = Counter(m["site"] for m in kept_meta)
    per_cat = Counter(m["category"] for m in kept_meta)
    total_steps = sum(m["steps"] for m in kept_meta)
    kept = len(kept_meta)
    stats = {
        "tasksAttempted": attempted,
        "trajectoriesKept": kept,
        "failures": failures,
        "successRate": round(kept / attempted, 4) if attempted else 0.0,
        "perSite": dict(per_site),
        "perCategory": dict(per_cat),
        "totalSteps": total_steps,
        "meanStepsPerTrajectory": round(total_steps / kept, 2) if kept else 0,
        "elapsedSeconds": round(elapsed, 1),
        "seed": seed,
    }
    tmp = STATS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(stats, f, indent=2)
    os.replace(tmp, STATS_PATH)
    return stats


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

    # Line-buffered stdout so progress is visible even when piped to a file.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(TRAJECTORIES_PATH), exist_ok=True)

    tasks = sample_tasks(args.n, seed=args.seed)
    print(f"[run] sampled {len(tasks)} tasks (requested {args.n}) seed={args.seed}", flush=True)

    exe = chromium_executable()
    print(f"[run] chromium executable: {exe or '(playwright default)'}", flush=True)

    # Pre-existing kept count (when --append) so stats stay cumulative.
    kept_meta: list[dict] = []
    if args.append and os.path.exists(TRAJECTORIES_PATH):
        with open(TRAJECTORIES_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                t = json.loads(line)
                kept_meta.append(
                    {"site": t["site"], "category": t["taskSpec"]["category"],
                     "steps": len(t["steps"])}
                )
        print(f"[run] --append: {len(kept_meta)} existing trajectories", flush=True)

    traj_file = open(TRAJECTORIES_PATH, "a" if args.append else "w")

    failures = 0
    rewards_log: list[dict] = []
    attempted = 0
    t0 = time.time()

    with sync_playwright() as p:
        launch_kwargs = {"args": ["--headless=new"]}
        if exe:
            launch_kwargs["executable_path"] = exe
        browser = p.chromium.launch(**launch_kwargs)

        for i, task in enumerate(tasks):
            site = task["site"]
            spec = task["taskSpec"]
            attempted += 1
            context = browser.new_context(
                viewport=VIEWPORT, device_scale_factor=1, base_url=BASE_URL
            )
            create_episode = make_episode_creator(context)
            try:
                traj = run_episode(context, site, spec, create_episode)
            except Exception as e:  # noqa: BLE001 -- never let one task kill the run
                traj = {"_failed": True, "reason": f"uncaught: {type(e).__name__}: {e}"}

            if traj.get("_failed"):
                failures += 1
                print(f"[{i+1}/{len(tasks)}] FAIL {site} {json.dumps(spec)} :: {traj.get('reason')}",
                      flush=True)
                context.close()
                write_stats(kept_meta, attempted, failures, time.time() - t0, args.seed)
                continue

            episode_id = traj["episodeId"]
            reward = fetch_reward(context, episode_id) or {}
            context.close()

            success = bool(reward.get("success"))
            rewards_log.append(
                {"episodeId": episode_id, "site": site, "taskSpec": spec,
                 "targetItemId": traj["targetItemId"], "success": success,
                 "scalar": reward.get("scalar"), "checkpointsHit": reward.get("checkpointsHit")}
            )

            if args.smoke:
                print(
                    f"[{i+1}/{len(tasks)}] {site} {json.dumps(spec)} target={traj['targetItemId']} "
                    f"-> success={success} scalar={reward.get('scalar')} "
                    f"checkpoints={reward.get('checkpointsHit')}/{reward.get('checkpointsTotal')} "
                    f"steps={len(traj['steps'])}",
                    flush=True,
                )

            if success:
                traj["reward"] = {
                    k: reward.get(k)
                    for k in ("success", "attrMatch", "checkpointsHit", "checkpointsTotal", "scalar")
                }
                # CRASH-SAFE: write + flush + fsync this trajectory now.
                traj_file.write(json.dumps(traj) + "\n")
                traj_file.flush()
                os.fsync(traj_file.fileno())
                kept_meta.append(
                    {"site": site, "category": spec["category"], "steps": len(traj["steps"])}
                )
                if not args.smoke:
                    print(
                        f"[{i+1}/{len(tasks)}] OK   {site} {json.dumps(spec)} "
                        f"target={traj['targetItemId']} steps={len(traj['steps'])} "
                        f"(kept={len(kept_meta)})",
                        flush=True,
                    )
            else:
                failures += 1
                if not args.smoke:
                    print(f"[{i+1}/{len(tasks)}] BAD  {site} {json.dumps(spec)} reward.success=false",
                          flush=True)

            write_stats(kept_meta, attempted, failures, time.time() - t0, args.seed)

        browser.close()

    traj_file.close()
    stats = write_stats(kept_meta, attempted, failures, time.time() - t0, args.seed)

    print("\n===== RUN SUMMARY =====", flush=True)
    print(json.dumps(stats, indent=2), flush=True)
    if args.smoke:
        print("\n===== SMOKE REWARDS =====", flush=True)
        for r in rewards_log:
            print(json.dumps(r), flush=True)
        all_ok = all(r["success"] for r in rewards_log) and len(rewards_log) == attempted
        print(f"\nSMOKE {'PASSED' if all_ok else 'FAILED'}: "
              f"{sum(r['success'] for r in rewards_log)}/{attempted} success", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
