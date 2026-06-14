"""Bundle a lean subset of the recorded buyer trajectories for Mission Control.

Reads (READ-ONLY) ../data/datasets/buyer/{trajectories.jsonl,images/} and writes:

  static/shots/<episodeId>_<step>.jpg   downscaled ~640px JPEG screenshots
  fleet.json                             compact replay manifest the server serves

We keep a SUBSET of trajectories (default 60) — more than enough to fill a ~100
tile grid by cycling — and we deliberately balance across the three sites and six
product categories so the grid looks varied. The full corpus is 399 trajectories /
~4,900 PNGs (~1 GB); the bundled subset is a few dozen MB of JPEG.

Each emitted trajectory step carries a human-readable `action_label` (e.g.
`type "Phones"`, `click (412, 233)`, `done ✓`) and a derived pipeline `status`
(searching → filtering → viewing → cart → checkout → done) so the front-end can
render a status badge straight from the manifest.

Usage:  python prep_data.py [--n 60] [--width 640] [--quality 72]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import defaultdict

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "data", "datasets", "buyer"))
SRC_TRAJ = os.path.join(SRC, "trajectories.jsonl")
SRC_IMG = os.path.join(SRC, "images")

OUT_SHOTS = os.path.join(HERE, "static", "shots")
OUT_MANIFEST = os.path.join(HERE, "fleet.json")

# Display names so a tile reads like a real marketplace tab, not "site-a".
SITE_NAMES = {"site-a": "kleinmarkt.a", "site-b": "kleinmarkt.b", "site-c": "kleinmarkt.c"}


def derive_status(steps, idx):
    """Map a position in the action sequence to a pipeline stage.

    The recorded runs are remarkably uniform: step 0 clicks the search box, step 1
    types the category, then a run of clicks navigates filters / a result / the
    product page / the cart, and the final step is `done`. We bucket by progress
    through the trajectory and by the action at `idx`.
    """
    a = steps[idx]["action"]
    act = a.get("action")
    n = len(steps)
    if act == "done":
        return "done"
    if act == "type":
        return "searching"
    if idx == 0:
        return "searching"
    # clicks: bucket by how far through the run we are
    frac = idx / max(n - 1, 1)
    if idx <= 1:
        return "searching"
    if frac < 0.45:
        return "filtering"
    if frac < 0.65:
        return "viewing"
    if frac < 0.85:
        return "cart"
    return "checkout"


def action_label(action):
    act = action.get("action")
    if act == "click":
        return f'click ({action.get("x")}, {action.get("y")})'
    if act == "type":
        return f'type "{action.get("text", "")}"'
    if act == "scroll":
        dy = action.get("dy") or action.get("y") or ""
        return f"scroll {dy}".strip()
    if act == "done":
        return "done ✓"
    return act or "?"


def goal_text(task_spec):
    cat = task_spec.get("category", "item")
    brand = task_spec.get("brand")
    if brand:
        return f"buy cheapest {cat} · {brand}"
    return f"buy cheapest {cat}"


def pick_subset(trajectories, n):
    """Round-robin across (site, category) buckets for visual variety."""
    buckets = defaultdict(list)
    for t in trajectories:
        key = (t.get("site"), t.get("taskSpec", {}).get("category"))
        buckets[key].append(t)
    keys = sorted(buckets.keys(), key=lambda k: (str(k[0]), str(k[1])))
    chosen, i = [], 0
    while len(chosen) < n and any(buckets[k] for k in keys):
        k = keys[i % len(keys)]
        if buckets[k]:
            chosen.append(buckets[k].pop(0))
        i += 1
    return chosen[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="trajectories to bundle")
    ap.add_argument("--width", type=int, default=640, help="downscaled JPEG width")
    ap.add_argument("--quality", type=int, default=72, help="JPEG quality")
    args = ap.parse_args()

    with open(SRC_TRAJ) as f:
        trajectories = [json.loads(line) for line in f if line.strip()]
    print(f"loaded {len(trajectories)} trajectories from {SRC_TRAJ}")

    subset = pick_subset(trajectories, args.n)
    print(f"selected {len(subset)} trajectories (balanced across site x category)")

    if os.path.isdir(OUT_SHOTS):
        shutil.rmtree(OUT_SHOTS)
    os.makedirs(OUT_SHOTS, exist_ok=True)

    manifest = {"meta": {}, "trajectories": []}
    n_shots = 0
    total_bytes = 0

    for t in subset:
        eid = t["episodeId"]
        steps_out = []
        for s in t["steps"]:
            src_png = s["image"]
            if not os.path.isfile(src_png):
                # manifest stores paths from this machine; tolerate a miss
                continue
            fname = f"{eid}_{s['step']}.jpg"
            dst = os.path.join(OUT_SHOTS, fname)
            with Image.open(src_png) as im:
                im = im.convert("RGB")
                w, h = im.size
                if w > args.width:
                    im = im.resize((args.width, round(h * args.width / w)), Image.LANCZOS)
                im.save(dst, "JPEG", quality=args.quality, optimize=True)
            total_bytes += os.path.getsize(dst)
            n_shots += 1
            steps_out.append(
                {
                    "step": s["step"],
                    "shot": fname,
                    "action": action_label(s["action"]),
                    "raw_action": s["action"].get("action"),
                    "status": derive_status(t["steps"], s["step"]),
                }
            )
        r = t.get("reward", {})
        manifest["trajectories"].append(
            {
                "episode_id": eid,
                "site": t.get("site"),
                "site_name": SITE_NAMES.get(t.get("site"), t.get("site")),
                "goal": goal_text(t.get("taskSpec", {})),
                "category": t.get("taskSpec", {}).get("category"),
                "n_steps": len(steps_out),
                "reward": r.get("scalar", 1),
                "success": bool(r.get("success", True)),
                "checkpoints": [r.get("checkpointsHit"), r.get("checkpointsTotal")],
                "steps": steps_out,
            }
        )

    # Aggregate stats over the FULL corpus (so the top bar shows the real 399-run
    # numbers, not just the bundled subset).
    n_traj = len(trajectories)
    n_succ = sum(1 for t in trajectories if t.get("reward", {}).get("success"))
    all_steps = [len(t["steps"]) for t in trajectories]
    total_steps = sum(all_steps)
    manifest["meta"] = {
        "corpus_trajectories": n_traj,
        "corpus_success": n_succ,
        "success_rate": round(n_succ / n_traj, 4) if n_traj else 0,
        "avg_steps": round(total_steps / n_traj, 2) if n_traj else 0,
        "total_steps": total_steps,
        "bundled_trajectories": len(manifest["trajectories"]),
        "model": "overfit Gemma-4 E2B",
        "sites": sorted({t.get("site") for t in trajectories}),
        "categories": sorted({t.get("taskSpec", {}).get("category") for t in trajectories}),
    }

    with open(OUT_MANIFEST, "w") as f:
        json.dump(manifest, f, separators=(",", ":"))

    print(f"wrote {n_shots} JPEGs ({total_bytes/1e6:.1f} MB) -> {OUT_SHOTS}")
    print(f"wrote manifest -> {OUT_MANIFEST}")
    print(f"meta: {json.dumps(manifest['meta'])}")


if __name__ == "__main__":
    main()
