"""Loop A, step 1 — build NEW router SFT examples from resolved HUMAN FEEDBACK.

The delegation router (Pioneer side-challenge) is first fine-tuned on synthetic,
self-consistent labels (pioneer/dataset.py). This module closes the loop: it turns
*real human corrections* into additional SFT examples in the EXACT same training
format, so a retrain learns from where the router was actually wrong.

Two feedback sources (both optional; we use whatever is reachable):

  (i)  Postgres `Escalation` rows with status = RESOLVED. These hold the live
       resolved-feedback signal (rating / correctedRole / correctedUrgency /
       rewardScalar / resolution / routing). Read via psycopg over DATABASE_URL
       (the public Railway proxy in .env).

  (ii) The legacy `data/router_rewards.jsonl` written by supervisor/reward.py —
       each line already carries {context, guardrail, predicted, corrected,
       human, reward}, i.e. a ready-made (situation -> corrected routing) pair.

For every kept feedback row we reconstruct a `DecisionRequest` + `Guardrail`,
render the user turn with pioneer.dataset.render_user (byte-identical to the base
training prompt), and emit the corrected target JSON as the assistant turn. We
PREFER high-signal rows: a corrected row (correctedRole/correctedUrgency present,
or rating==good with a clear label) teaches the decision surface; low-reward rows
with no correction are dropped (they say "this was wrong" but not "do THIS").

Output:  data/datasets/router_sft_feedback.jsonl   (chat-format SFT, same schema)

Run (dry-run friendly — never writes/trains anything remote):
    python pioneer/feedback_dataset.py --stats
    python pioneer/feedback_dataset.py --out data/datasets/router_sft_feedback.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(ROOT / ".env"), override=True)

from shared.contracts.schema import (  # noqa: E402
    DecisionRequest,
    DecisionType,
    Guardrail,
    Item,
    TargetPerson,
    UrgencyTier,
)
from pioneer.dataset import _SYS, render_user  # noqa: E402

REWARD_LOG = ROOT / "data" / "router_rewards.jsonl"
OUT_DEFAULT = ROOT / "data" / "datasets" / "router_sft_feedback.jsonl"

# Only emit examples we actually trust as a *positive* training target.
DEFAULT_MIN_REWARD = 0.0  # rows below this with no correction are dropped

_PERSON_VALUES = {p.value for p in TargetPerson}
_URGENCY_VALUES = {u.value for u in UrgencyTier}

# purchasing-role taxonomy (policy-v1) -> legacy TargetPerson the SFT target uses.
_ROLE_TO_PERSON = {
    "buyer": "buyer",
    "procurement_lead": "procurement_lead",
    "procurement": "procurement_lead",
    "manager": "manager",
    "none": "none",
    None: None,
}


# ───────────────────────── helpers ──────────────────────────────────────────
def _coerce_person(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = _ROLE_TO_PERSON.get(value, value)
    return v if v in _PERSON_VALUES else None


def _coerce_urgency(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value if value in _URGENCY_VALUES else None


def _guardrail_from_dict(d: Optional[dict]) -> Guardrail:
    """Rebuild a Guardrail, tolerating missing/partial dicts."""
    if not d:
        return Guardrail()
    try:
        return Guardrail.model_validate(d)
    except Exception:
        # keep only the fields we recognise; never crash on a stray key
        keep = {k: d.get(k) for k in (
            "needs_signoff", "urgency_prior", "counter_offer", "pickup_time",
            "pickup_location", "condition", "commitments", "extractor",
        ) if k in d}
        try:
            return Guardrail.model_validate(keep)
        except Exception:
            return Guardrail()


def _sft_record(req: DecisionRequest, guardrail: Guardrail, target: dict) -> dict:
    """One chat-format SFT line, identical in shape to pioneer/dataset.py."""
    return {
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": render_user(req, guardrail)},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ]
    }


def _valid_target(t: dict) -> bool:
    return (
        isinstance(t.get("should_delegate"), bool)
        and t.get("target_person") in _PERSON_VALUES
        and t.get("urgency_tier") in _URGENCY_VALUES
        and isinstance(t.get("suggested_message"), str)
    )


# ───────────────────────── source (ii): legacy jsonl ────────────────────────
def from_reward_log(path: Path = REWARD_LOG, min_reward: float = DEFAULT_MIN_REWARD):
    """Yield (sft_record, meta) from data/router_rewards.jsonl.

    Each record already has the corrected routing. We keep a row if it carries a
    usable corrected label AND (it was rated good/partial OR a correction was made
    OR its reward clears the floor). The target is the *corrected* output, which is
    exactly what the next model should imitate.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        ctx = rec.get("context")
        if not ctx:
            continue
        corrected = rec.get("corrected") or {}
        human = rec.get("human") or {}
        reward = rec.get("reward", 0.0)
        rating = human.get("rating")
        had_correction = bool(human.get("corrected_person") or human.get("corrected_urgency"))

        # keep rule: trust the corrected label when it was a good outcome OR an
        # explicit human correction OR the reward floor is met.
        keep = (rating in ("good", "partial")) or had_correction or (reward >= min_reward)
        if not keep:
            continue

        person = _coerce_person(corrected.get("target_person"))
        urgency = _coerce_urgency(corrected.get("urgency_tier"))
        should = corrected.get("should_delegate")
        if person is None or urgency is None or not isinstance(should, bool):
            continue

        try:
            req = DecisionRequest.model_validate(ctx)
        except Exception:
            continue
        guardrail = _guardrail_from_dict(rec.get("guardrail"))

        msg = human.get("notes") or ctx.get("situation_text", "")[:160] or ""
        target = {
            "should_delegate": should,
            "target_person": person,
            "urgency_tier": urgency,
            "suggested_message": msg,
        }
        if not _valid_target(target):
            continue
        yield _sft_record(req, guardrail, target), {
            "source": "reward_log", "request_id": rec.get("request_id"),
            "reward": reward, "rating": rating, "corrected": had_correction,
        }


# ───────────────────────── source (i): Postgres Escalation ──────────────────
_ESCALATION_SQL = """
SELECT "requestId", "orgId", "decisionType", "situationText",
       "proposedValueCents", "budgetCapCents", "agentConfidence",
       "shouldDelegate", "targetPurchasingRole", "urgencyTier",
       "suggestedMessage", "rating", "correctedRole", "correctedUrgency",
       "rewardScalar", "resolution", "routing", "guardrail"
FROM "Escalation"
WHERE status = 'RESOLVED'
ORDER BY "resolvedAt" DESC NULLS LAST
LIMIT %s
"""

# Escalation.urgencyTier is the enum UrgencyTier (ASYNC|URGENT_PUSH|VOICE).
_DBURGENCY_TO_VALUE = {
    "ASYNC": "async", "URGENT_PUSH": "urgent_push", "VOICE": "voice",
    "async": "async", "urgent_push": "urgent_push", "voice": "voice",
}


def _decision_type(value: Optional[str]) -> DecisionType:
    try:
        return DecisionType(value)
    except Exception:
        return DecisionType.approve_purchase


def from_postgres(database_url: Optional[str] = None, limit: int = 5000,
                  min_reward: float = DEFAULT_MIN_REWARD):
    """Yield (sft_record, meta) from RESOLVED Escalation rows.

    Reachable-but-empty is the expected state pre-demo (the live app hasn't logged
    resolutions yet) — we simply yield nothing. Any connection error is swallowed
    by the caller (collect) so the legacy source still produces a dataset.
    """
    try:
        import psycopg  # noqa: F401  (psycopg3)
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "psycopg not installed — `pip install 'psycopg[binary]'` into the .venv"
        ) from e
    import psycopg

    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set (read from .env)")

    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(_ESCALATION_SQL, (limit,))
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()

    for row in rows:
        r = dict(zip(cols, row))
        reward = r.get("rewardScalar")
        rating = r.get("rating")
        # corrected label preferred, else the routed decision the human accepted.
        person = _coerce_person(r.get("correctedRole")) or _coerce_person(r.get("targetPurchasingRole"))
        urgency = (
            _coerce_urgency(_DBURGENCY_TO_VALUE.get(r.get("correctedUrgency") or "", r.get("correctedUrgency")))
            or _coerce_urgency(_DBURGENCY_TO_VALUE.get(r.get("urgencyTier") or "", r.get("urgencyTier")))
        )
        had_correction = bool(r.get("correctedRole") or r.get("correctedUrgency"))

        keep = (rating in ("good", "partial")) or had_correction or (
            reward is not None and reward >= min_reward
        )
        if not keep:
            continue
        if person is None or urgency is None:
            continue
        should = r.get("shouldDelegate")
        if should is None:
            should = True

        proposed = (r["proposedValueCents"] / 100.0) if r.get("proposedValueCents") is not None else None
        budget = (r["budgetCapCents"] / 100.0) if r.get("budgetCapCents") is not None else None
        item = None
        if proposed is not None:
            item = Item(title=(r.get("situationText") or "item")[:60], listed_price=proposed)

        req = DecisionRequest(
            request_id=r.get("requestId") or "fb",
            org_id=r.get("orgId") or "org-acme",
            decision_type=_decision_type(r.get("decisionType")),
            situation_text=r.get("situationText") or "",
            item=item,
            proposed_value=proposed,
            budget_cap=budget,
            agent_confidence=float(r.get("agentConfidence") or 0.5),
        )
        guardrail = _guardrail_from_dict(r.get("guardrail"))
        target = {
            "should_delegate": bool(should),
            "target_person": person,
            "urgency_tier": urgency,
            "suggested_message": r.get("suggestedMessage") or (r.get("situationText") or "")[:160],
        }
        if not _valid_target(target):
            continue
        yield _sft_record(req, guardrail, target), {
            "source": "postgres", "request_id": r.get("requestId"),
            "reward": reward, "rating": rating, "corrected": had_correction,
        }


# ───────────────────────── collect + write ──────────────────────────────────
def collect(min_reward: float = DEFAULT_MIN_REWARD, use_postgres: bool = True,
            use_reward_log: bool = True):
    """Gather feedback SFT records from both sources. Returns (records, summary)."""
    records = []
    summary = {"reward_log": 0, "postgres": 0, "postgres_status": "skipped", "dropped": 0}

    if use_reward_log:
        for rec, _meta in from_reward_log(min_reward=min_reward):
            records.append(rec)
            summary["reward_log"] += 1

    if use_postgres:
        try:
            n0 = len(records)
            for rec, _meta in from_postgres(min_reward=min_reward):
                records.append(rec)
            summary["postgres"] = len(records) - n0
            summary["postgres_status"] = (
                "ok" if summary["postgres"] > 0 else "reachable-empty"
            )
        except Exception as e:
            summary["postgres_status"] = f"unreachable: {type(e).__name__}: {str(e)[:120]}"

    summary["total"] = len(records)
    return records, summary


def write(records: Iterable[dict], out: Path = OUT_DEFAULT) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return n


def build(out: Path = OUT_DEFAULT, min_reward: float = DEFAULT_MIN_REWARD,
          use_postgres: bool = True, use_reward_log: bool = True,
          write_file: bool = True):
    records, summary = collect(min_reward=min_reward, use_postgres=use_postgres,
                               use_reward_log=use_reward_log)
    if write_file:
        write(records, out)
        summary["out"] = str(out)
    return records, summary


def _print_summary(summary: dict, records, sample: bool = True) -> None:
    print(f"feedback SFT examples : {summary['total']}")
    print(f"  from reward_log     : {summary['reward_log']}  ({REWARD_LOG})")
    print(f"  from postgres       : {summary['postgres']}  (status: {summary['postgres_status']})")
    if "out" in summary:
        print(f"wrote -> {summary['out']}")
    if sample and records:
        ex = records[0]
        target = json.loads(ex["messages"][2]["content"])
        print("\nsample target (assistant):", json.dumps(target, ensure_ascii=False))
        print("sample user (first 220c)  :", ex["messages"][1]["content"][:220], "...")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--min-reward", type=float, default=DEFAULT_MIN_REWARD)
    ap.add_argument("--no-postgres", action="store_true", help="skip the Postgres source")
    ap.add_argument("--no-reward-log", action="store_true", help="skip the legacy jsonl source")
    ap.add_argument("--stats", action="store_true",
                    help="dry-run: build in memory and print counts, do NOT write the file")
    args = ap.parse_args()

    records, summary = build(
        out=Path(args.out),
        min_reward=args.min_reward,
        use_postgres=not args.no_postgres,
        use_reward_log=not args.no_reward_log,
        write_file=not args.stats,
    )
    _print_summary(summary, records)
    if summary["total"] == 0:
        print("\n(no feedback examples produced — no resolved feedback yet. This is a "
              "valid empty state, not an error.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
