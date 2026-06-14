"""Loop B — vision buyer-policy EXPERT ITERATION.

Closes the buyer-vision self-improvement loop:

  (a) pull recent fleet EPISODES + their reward. We read the marketplace's reward
      ORACLE — either over HTTP (GET {MARKETPLACE_URL}/api/reward?episodeId=...) or,
      when the server isn't up, straight from the marketplace SQLite
      (apps/marketplace/prisma/dev.db Episode/Event tables, replayed through the same
      reward weights). The recorded fleet TRAJECTORIES (screenshots + the action taken
      at each step) live in data/datasets/buyer/trajectories.jsonl, keyed by episodeId.

  (b) keep only EXPERT trajectories: reward.success is true AND the trajectory is not
      bloated — steps <= (oracle optimal steps) + SLACK. The "oracle optimal" is the
      shortest successful trajectory observed (the funnel takes ~`checkpointsTotal`
      milestones; padded UI actions push real runs a little longer). This is exactly
      expert iteration: imitate only the good, efficient rollouts.

  (c) convert each kept trajectory's steps to the SAME vision SFT format the Modal
      fine-tune consumes (vision_ft/build_dataset.iter_examples: a user turn with an
      {image}+{text} block and an assistant turn whose text is the action JSON), and
      APPEND the new examples to the training dataset (data/datasets/buyer/sft.jsonl),
      so the next `modal run` trains on base + freshly-distilled expert data.

  (d) print a summary + the EXACT `modal run` retrain command and the redeploy
      command. The actual remote training is GUARDED behind --submit (default dry-run):
      a Modal vision fine-tune is ~1h and costs real money, so we never auto-launch it.

Run (dry-run, safe — never trains/deploys):
    set -a; source ../.env; set +a              # (optional) MARKETPLACE_URL etc.
    .venv/bin/python expert_iteration.py --stats        # counts only, write nothing
    .venv/bin/python expert_iteration.py                # build + append SFT, print plan
    .venv/bin/python expert_iteration.py --submit       # ALSO launch the Modal train

Sources are tried in order: HTTP oracle (if reachable) then SQLite; either alone is
enough. If neither yields a usable episode we emit a correctly-empty batch with a
clear reason rather than a crash.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))   # build_dataset is a sibling module
sys.path.insert(0, str(ROOT))

import build_dataset  # noqa: E402  (vision_ft/build_dataset.py)

# Reward weights mirror apps/marketplace/src/lib/reward.ts so the SQLite path
# produces the SAME scalar the HTTP oracle would.
CHECKPOINT_ORDER = [
    "SEARCH_SUBMITTED", "FILTER_APPLIED", "PRODUCT_VIEWED",
    "ADD_TO_CART", "CHECKOUT_STARTED", "ORDER_PLACED",
]
W_SUCCESS, W_ATTR, W_CHECKPOINTS = 0.6, 0.25, 0.15

TRAJ_PATH = ROOT / "data" / "datasets" / "buyer" / "trajectories.jsonl"
SFT_PATH = ROOT / "data" / "datasets" / "buyer" / "sft.jsonl"
DEV_DB = ROOT / "apps" / "marketplace" / "prisma" / "dev.db"
MARKETPLACE_URL = os.environ.get("MARKETPLACE_URL", "http://localhost:3000").rstrip("/")

DEFAULT_SLACK = 2  # steps <= oracle_optimal + SLACK


# ───────────────────────── reward sources ───────────────────────────────────
def reward_from_sqlite(episode_id: str, db_path: Path = DEV_DB) -> Optional[dict]:
    """Replay an episode's events from the marketplace SQLite, returning a reward
    dict shaped like the /api/reward oracle ({success, scalar, steps, checkpoints*})."""
    if not db_path.exists():
        return None
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        row = cur.execute(
            'SELECT "targetItemId","targetAttrs" FROM "Episode" WHERE id=?',
            (episode_id,),
        ).fetchone()
        if row is None:
            return None
        target_item_id, target_attrs_raw = row
        target_attrs = json.loads(target_attrs_raw) if target_attrs_raw else None
        events = cur.execute(
            'SELECT type,payload FROM "Event" WHERE episodeId=? ORDER BY step ASC',
            (episode_id,),
        ).fetchall()
    finally:
        con.close()

    seen = set()
    order_attrs = None
    order_item = None
    success = False
    for etype, payload_raw in events:
        if etype in CHECKPOINT_ORDER:
            seen.add(etype)
        if etype == "ORDER_PLACED":
            payload = json.loads(payload_raw) if payload_raw else {}
            iid = payload.get("itemId")
            try:
                iid = int(iid)
            except (TypeError, ValueError):
                iid = None
            if iid is not None:
                order_item = iid
                if target_item_id is not None and iid == target_item_id:
                    success = True
            if isinstance(payload.get("attrs"), dict):
                order_attrs = payload["attrs"]

    checkpoints_hit = len(seen)
    attr_match = 0.0
    if target_attrs and order_attrs:
        score = 0
        if order_attrs.get("category") == target_attrs.get("category"):
            score += 1
        if order_attrs.get("brand") == target_attrs.get("brand"):
            score += 1
        op, tp = order_attrs.get("priceCents"), target_attrs.get("priceCents")
        if isinstance(op, (int, float)) and isinstance(tp, (int, float)) and op <= tp:
            score += 1
        attr_match = score / 3
    elif success:
        attr_match = 1.0

    cp_frac = checkpoints_hit / len(CHECKPOINT_ORDER)
    scalar = W_SUCCESS * (1 if success else 0) + W_ATTR * attr_match + W_CHECKPOINTS * cp_frac
    return {
        "success": success,
        "attrMatch": attr_match,
        "checkpointsHit": checkpoints_hit,
        "checkpointsTotal": len(CHECKPOINT_ORDER),
        "steps": len(events),
        "scalar": round(scalar, 4),
        "orderedItemId": order_item,
        "_source": "sqlite",
    }


def reward_from_http(episode_id: str, base_url: str = MARKETPLACE_URL,
                     timeout: float = 8.0) -> Optional[dict]:
    """GET the reward oracle over HTTP. None on any transport/HTTP error."""
    try:
        import httpx
        r = httpx.get(f"{base_url}/api/reward", params={"episodeId": episode_id},
                      timeout=timeout)
        if r.status_code != 200:
            return None
        d = r.json()
        d["_source"] = "http"
        return d
    except Exception:
        return None


def get_reward(episode_id: str, inline: Optional[dict], prefer_http: bool,
               http_ok: bool) -> Optional[dict]:
    """Resolve a reward for an episode from the best available source. We prefer the
    live oracle (HTTP or SQLite); the trajectory's INLINE reward is the final fallback
    (it was written by the same oracle at capture time)."""
    if prefer_http and http_ok:
        r = reward_from_http(episode_id)
        if r is not None:
            return r
    r = reward_from_sqlite(episode_id)
    if r is not None:
        return r
    if inline:
        out = dict(inline)
        out.setdefault("steps", inline.get("steps"))
        out["_source"] = "inline"
        return out
    return None


# ───────────────────────── selection (expert iteration) ─────────────────────
def load_trajectories(path: Path = TRAJ_PATH, recent: Optional[int] = None) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if recent is not None:
        rows = rows[-recent:]
    return rows


def select_expert(trajectories: list[dict], slack: int, prefer_http: bool,
                  http_ok: bool) -> tuple[list[dict], dict]:
    """Keep only successful, non-bloated trajectories. The oracle-optimal step count
    is the shortest successful trajectory observed; we keep runs within +slack of it.
    Returns (kept, summary)."""
    rewarded = []
    for t in trajectories:
        eid = t.get("episodeId")
        if not eid:
            continue
        reward = get_reward(eid, t.get("reward"), prefer_http, http_ok)
        if reward is None:
            continue
        n_steps = len(t.get("steps") or [])
        rewarded.append((t, reward, n_steps))

    successful = [(t, r, n) for (t, r, n) in rewarded if r.get("success")]
    if not successful:
        return [], {
            "episodes_seen": len(trajectories),
            "with_reward": len(rewarded),
            "successful": 0,
            "oracle_optimal_steps": None,
            "kept": 0,
            "reason": "no successful episodes with a reward — nothing to imitate",
            "sources": sorted({r.get("_source") for (_, r, _) in rewarded}),
        }

    oracle_optimal = min(n for (_, _, n) in successful)
    budget = oracle_optimal + slack
    kept = [t for (t, _r, n) in successful if n <= budget]
    return kept, {
        "episodes_seen": len(trajectories),
        "with_reward": len(rewarded),
        "successful": len(successful),
        "oracle_optimal_steps": oracle_optimal,
        "step_budget": budget,
        "kept": len(kept),
        "sources": sorted({r.get("_source") for (_, r, _) in rewarded}),
    }


# ───────────────────────── SFT conversion (matches build_dataset) ───────────
def trajectory_to_sft(traj: dict) -> list[dict]:
    """Convert one kept trajectory to vision SFT examples in the EXACT format the
    Modal fine-tune consumes (build_dataset.iter_examples). One example per step that
    has both a screenshot and a structured action."""
    user_text = build_dataset._user_text(traj)
    out = []
    for step in traj.get("steps", []):
        img = step.get("image")
        action = step.get("action")
        if not img or not isinstance(action, dict):
            continue
        out.append({
            "messages": [
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": user_text},
                ]},
                {"role": "assistant", "content": [
                    {"type": "text", "text": build_dataset._action_json(action)},
                ]},
            ],
            "image": img,
        })
    return out


def build_batch(kept: list[dict]) -> list[dict]:
    batch = []
    for t in kept:
        batch.extend(trajectory_to_sft(t))
    return batch


def append_to_dataset(batch: list[dict], sft_path: Path = SFT_PATH) -> int:
    """Append the new expert examples to the training SFT dataset. The Modal full_train
    builds from trajectories.jsonl directly, but the .jsonl SFT mirror is the artifact
    other tooling reads, so we keep it in sync."""
    sft_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with sft_path.open("a") as f:
        for ex in batch:
            # the .jsonl SFT mirror stores the full chat record; the image PATH is
            # carried so the Modal loader can attach the PIL image.
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            n += 1
    return n


# ───────────────────────── plan printing ────────────────────────────────────
def _print_plan(summary: dict, batch_n: int, appended: Optional[int],
                submit: bool, sft_path: Path) -> None:
    print("=" * 70)
    print("Loop B — vision buyer-policy expert iteration (reward -> expert SFT)")
    print("=" * 70)
    print(f"episodes seen        : {summary['episodes_seen']}  "
          f"(reward sources: {', '.join(summary.get('sources') or ['none'])})")
    print(f"with a reward        : {summary['with_reward']}")
    print(f"successful           : {summary['successful']}")
    if summary.get("oracle_optimal_steps") is not None:
        print(f"oracle optimal steps : {summary['oracle_optimal_steps']}  "
              f"(keep steps <= {summary['step_budget']})")
    print(f"expert trajectories  : {summary['kept']}")
    if summary.get("reason"):
        print(f"note                 : {summary['reason']}")
    print(f"new SFT examples      : {batch_n}  (one per expert step)")
    if appended is not None:
        print(f"appended -> {sft_path}  (+{appended} lines)")
    print()
    print("WOULD retrain on Modal with base + the newly-distilled expert data:")
    print("  # 1. stage the dataset onto the Modal volume")
    print("  modal run vision_ft/modal_app.py::upload_dataset")
    print("  # 2. launch the LoRA fine-tune (guarded; ~1h, costs real money)")
    print("  modal run vision_ft/modal_app.py::full_train --i-have-signoff")
    print("  # 3. redeploy the serving endpoint with the new adapter")
    print("  modal deploy vision_ft/serve_modal.py")
    print()
    if not submit:
        print("DRY-RUN (default): no Modal job launched, no deploy.")
        print("  A full vision fine-tune is ~1h and bills real GPU time, so we never")
        print("  auto-run it. Re-run with --submit to launch upload_dataset + full_train.")
    print("=" * 70)


# ───────────────────────── main ─────────────────────────────────────────────
def run(slack: int, recent: Optional[int], prefer_http: bool, write_file: bool,
        submit: bool) -> dict:
    if not TRAJ_PATH.exists():
        raise SystemExit(f"missing fleet trajectories {TRAJ_PATH}")

    http_ok = False
    if prefer_http:
        # one cheap probe so we don't pay HTTP latency per-episode if the server is down
        probe = reward_from_http("__probe__")
        http_ok = probe is not None or _server_up()

    trajectories = load_trajectories(recent=recent)
    kept, summary = select_expert(trajectories, slack, prefer_http, http_ok)
    batch = build_batch(kept)

    appended = None
    if write_file and batch:
        appended = append_to_dataset(batch)

    _print_plan(summary, len(batch), appended, submit, SFT_PATH)
    summary["new_sft_examples"] = len(batch)
    summary["appended"] = appended
    return summary


def _server_up() -> bool:
    try:
        import httpx
        # any 2xx/4xx (not a connection error) means the route exists
        r = httpx.get(f"{MARKETPLACE_URL}/api/reward", timeout=4.0)
        return r.status_code in (200, 400, 404)
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slack", type=int, default=DEFAULT_SLACK,
                    help="keep successful trajectories with steps <= oracle_optimal + slack")
    ap.add_argument("--recent", type=int, default=None,
                    help="only consider the most recent N episodes (default: all)")
    ap.add_argument("--no-http", action="store_true",
                    help="skip the HTTP oracle; read reward only from SQLite/inline")
    ap.add_argument("--stats", action="store_true",
                    help="dry-run: compute + print counts, do NOT append to the SFT file")
    ap.add_argument("--submit", action="store_true",
                    help="ALSO launch the Modal fine-tune (default: print the command only)")
    args = ap.parse_args()

    summary = run(
        slack=args.slack,
        recent=args.recent,
        prefer_http=not args.no_http,
        write_file=not args.stats,
        submit=args.submit,
    )

    if summary.get("new_sft_examples", 0) == 0:
        print("\n(no expert examples produced — see the note above. This is a valid "
              "empty state, not an error.)")
        return 0

    if args.submit:
        return _submit_modal()
    return 0


def _submit_modal() -> int:
    """Launch the Modal upload + full_train. Guarded entrypoint — only reached with
    --submit. Shells out to the modal CLI so we reuse the exact deploy path."""
    import shutil
    import subprocess

    modal_bin = shutil.which("modal") or str(HERE / ".venv" / "bin" / "modal")
    app = str(HERE / "modal_app.py")
    print(f"\n[submit] modal run {app}::upload_dataset")
    up = subprocess.run([modal_bin, "run", f"{app}::upload_dataset"])
    if up.returncode != 0:
        print("[submit] upload_dataset failed; aborting before training.")
        return up.returncode
    print(f"[submit] modal run {app}::full_train --i-have-signoff")
    tr = subprocess.run([modal_bin, "run", f"{app}::full_train", "--i-have-signoff"])
    if tr.returncode == 0:
        print("[submit] training launched. Redeploy serving with:")
        print("    modal deploy vision_ft/serve_modal.py")
    return tr.returncode


if __name__ == "__main__":
    raise SystemExit(main())
