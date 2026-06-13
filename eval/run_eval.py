"""Delegation-router eval: how well does each model reproduce the org's routing
*policy* (who to ping, how urgently, whether to delegate at all)?

Gold labels come from our rules engine (the policy spec). The story for the
Pioneer side-challenge: a small fine-tuned model reproduces this policy MORE
accurately, FASTER, and CHEAPER than a general-purpose frontier API call.

Contenders are pluggable: frontier (Gemini / OpenAI) now, the Pioneer-fine-tuned
model once its id is set in PIONEER_ROUTER_MODEL.

    python eval/run_eval.py --limit 60
    python eval/run_eval.py --limit 200 --models gemini:gemini-2.5-flash,gemini:gemini-2.5-pro
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)  # .env wins over any stale key exported in the shell

EVAL_PATH = Path(__file__).resolve().parent.parent / "data" / "datasets" / "router_eval.jsonl"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "results.json"

# rough 2026 list prices, USD per 1M tokens (input, output) — estimates for the cost slide
PRICES = {
    "gpt-5.5-chat-latest": (1.25, 10.0),
    "gpt-5.5": (1.25, 10.0),
    "gpt-5.4": (1.25, 10.0),
    "gpt-5.4-mini": (0.25, 2.0),
    "gpt-5-mini": (0.25, 2.0),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3-pro-preview": (2.0, 12.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
    "_pioneer": (0.05, 0.10),  # ~4B self-hosted-class; tiny
}
FIELDS = ("should_delegate", "target_person", "urgency_tier")


def load_eval(limit: int):
    rows = []
    for line in EVAL_PATH.read_text().splitlines()[:limit]:
        msgs = json.loads(line)["messages"]
        system = msgs[0]["content"]
        user = msgs[1]["content"]
        gold = json.loads(msgs[2]["content"])
        rows.append((system, user, gold))
    return rows


# ── providers: return (text, latency_ms, in_tok, out_tok) ─────────────────────
def call_gemini(model, system, user):
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    t = time.perf_counter()
    r = httpx.post(url, json=body, timeout=60)
    dt = (time.perf_counter() - t) * 1000
    r.raise_for_status()
    j = r.json()
    text = j["candidates"][0]["content"]["parts"][0]["text"]
    um = j.get("usageMetadata", {})
    return text, dt, um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0)


def call_openai(model, system, user, base_url=None, key_env="OPENAI_API_KEY"):
    from openai import OpenAI

    client = OpenAI(api_key=os.environ[key_env], base_url=base_url)
    kw = dict(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    t = time.perf_counter()
    try:
        resp = client.chat.completions.create(temperature=0, **kw)  # classic models
    except Exception:
        resp = client.chat.completions.create(**kw)  # gpt-5.x reasoning models reject temperature
    dt = (time.perf_counter() - t) * 1000
    u = resp.usage
    return resp.choices[0].message.content, dt, u.prompt_tokens, u.completion_tokens


def make_caller(spec):
    """spec = 'gemini:<model>' | 'openai:<model>' | 'pioneer:<model>'"""
    provider, _, model = spec.partition(":")
    if provider == "gemini":
        return model, lambda s, u: call_gemini(model, s, u)
    if provider == "openai":
        return model, lambda s, u: call_openai(model, s, u)
    if provider == "pioneer":
        base = os.getenv("PIONEER_BASE_URL", "https://api.pioneer.ai/v1")
        return model, lambda s, u: call_openai(model, s, u, base_url=base, key_env="PIONEER_API_KEY")
    raise ValueError(f"unknown provider in {spec}")


def parse_pred(text):
    try:
        d = json.loads(text)
    except Exception:
        # tolerate code fences / stray prose
        s, e = text.find("{"), text.rfind("}")
        d = json.loads(text[s : e + 1]) if s >= 0 < e else {}
    return {k: d.get(k) for k in FIELDS}


def evaluate(spec, rows):
    model, call = make_caller(spec)
    hits = {f: 0 for f in FIELDS}
    exact = 0
    lat, intok, outok, ok = [], 0, 0, 0
    for system, user, gold in rows:
        try:
            text, dt, it, ot = call(system, user)
        except Exception as e:
            print(f"   [{spec}] call failed: {repr(e)[:120]}")
            return None
        pred = parse_pred(text)
        lat.append(dt)
        intok += it
        outok += ot
        ok += 1
        all_ok = True
        for f in FIELDS:
            g = gold.get(f)
            p = pred.get(f)
            # normalise booleans that came back as strings
            if isinstance(g, bool):
                p = str(p).lower() in ("true", "1", "yes") if not isinstance(p, bool) else p
            if p == g:
                hits[f] += 1
            else:
                all_ok = False
        exact += all_ok
    n = ok
    pin, pout = PRICES.get(model, PRICES.get("_pioneer"))
    cost_per_1k = ((intok / n) * pin + (outok / n) * pout) / 1_000_000 * 1000
    lat.sort()
    return {
        "model": model,
        "n": n,
        "person_acc": hits["target_person"] / n,
        "urgency_acc": hits["urgency_tier"] / n,
        "delegate_acc": hits["should_delegate"] / n,
        "exact_match": exact / n,
        "p50_ms": lat[len(lat) // 2],
        "cost_per_1k_usd": round(cost_per_1k, 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument(
        "--models",
        default="openai:gpt-5.5-chat-latest,openai:gpt-5.4-mini,gemini:gemini-3.5-flash,gemini:gemini-3.1-pro-preview",
    )
    args = ap.parse_args()

    rows = load_eval(args.limit)
    print(f"eval set: {len(rows)} held-out examples (gold = org routing policy)\n")
    results = []
    for spec in args.models.split(","):
        spec = spec.strip()
        print(f"running {spec} ...")
        res = evaluate(spec, rows)
        if res:
            results.append(res)

    hdr = f"{'model':<26}{'person':>8}{'urgency':>9}{'delegate':>10}{'exact':>8}{'p50 ms':>9}{'$/1k':>9}"
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in results:
        print(
            f"{r['model']:<26}{r['person_acc']:>7.0%}{r['urgency_acc']:>9.0%}"
            f"{r['delegate_acc']:>10.0%}{r['exact_match']:>8.0%}{r['p50_ms']:>8.0f}{r['cost_per_1k_usd']:>9.3f}"
        )
    print("\n(gold labels come from the rules policy; a fine-tuned model that matches")
    print(" the policy better/cheaper/faster than these frontier calls wins the slide.)")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"limit": args.limit, "results": results}, indent=2))
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
