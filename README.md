# Quartermaster

An orchestration layer where a fleet of **buyer agents** shop marketplace clones we
own, and a **supervisor** pulls the *right human* in at the *right urgency* on their
phone. Both the agents and the supervisor **self-improve from reward signals**.

Built for the {Tech: Europe} hackathon. Plan: `~/.claude/plans/tidy-meandering-mochi.md`.

### The three beats
1. **Right person, right urgency** — the supervisor routes each agent escalation to
   buyer / procurement / manager at async / urgent-push / voice tiers.
2. **Scaled computer use by overfitting** — a small Gemma 4 vision model overfit to
   *our* pages, run ~100× in parallel.
3. **Both self-improve** — buyer policy from backend ground-truth reward; delegation
   router from human ratings (fine-tuned on **Pioneer**).

## Repo layout

```
shared/contracts/   handoff contract (DecisionRequest / RoutingDecision / HumanResolution)
supervisor/         guardrail (GLiNER2 + fallback), router, reward, store, FastAPI app
delivery/           delivery backends (local stub now; Telegram + voice next)
config/org.yaml     person -> chat_id -> budget routing table
demo/               scenarios + live simulate_agent
scripts/            check_delegation.py (offline end-to-end check)
data/               reward logs / datasets (gitignored)
apps/marketplace/   marketplace clones + reward oracle            [coming]
agent/              DOM oracle, fine-tune, fleet, Mission Control  [coming]
pioneer/            synthetic data, SFT/GRPO, adaptive inference   [coming]
eval/               Pioneer-vs-frontier harness                    [coming]
```

## Quick start (delegation supervisor — no keys needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# offline end-to-end check (routing table + reward loop):
python scripts/check_delegation.py

# or run the service + live demo:
uvicorn supervisor.app:app --reload      # terminal 1
python demo/simulate_agent.py            # terminal 2
```

The guardrail uses fast regex by default. To enable the real GLiNER2 extractor:
`pip install 'gliner2[local]'` (CPU, ~50ms/call) — the code auto-detects it.

## Configuration

Copy `.env.example` → `.env` and fill keys as you get them. Everything degrades
gracefully: no `TELEGRAM_BOT_TOKEN` → console stub; no `PIONEER_*` → rules router.
Set per-person `chat_id`s in `config/org.yaml` to enable real Telegram delivery.
