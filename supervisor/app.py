"""Quartermaster supervisor service.

  POST /escalate            buyer agent submits a DecisionRequest -> RoutingDecision
  POST /resolve/{id}        human (or Telegram callback) submits a HumanResolution
  GET  /resolution/{id}     buyer agent polls for the human's answer
  GET  /pending             open delegations (for a human UI / CLI)
  GET  /health
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException

from shared.contracts.schema import DecisionRequest, HumanResolution, RoutingDecision
from supervisor import dispatch, reward
from supervisor.guardrail import extract_guardrail
from supervisor.router import get_router
from supervisor.store import STORE

app = FastAPI(title="Quartermaster Supervisor", version="0.1.0")
_router = get_router()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "router": _router.version, "delivery": dispatch.get_delivery().name}


@app.post("/escalate", response_model=RoutingDecision)
def escalate(req: DecisionRequest) -> RoutingDecision:
    guardrail = extract_guardrail(req)
    decision = _router.route(req, guardrail)
    STORE.add(req, decision)
    if decision.should_delegate:
        dispatch.dispatch(req, decision)
    return decision


@app.post("/resolve/{request_id}", response_model=HumanResolution)
def resolve(request_id: str, resolution: HumanResolution) -> HumanResolution:
    req = STORE.requests.get(request_id)
    decision = STORE.decisions.get(request_id)
    if not req or not decision:
        raise HTTPException(status_code=404, detail="unknown request_id")
    resolution.request_id = request_id
    STORE.resolve(resolution)
    reward.log_reward(req, decision, resolution)
    # push the resolution back to the agent (fire-and-forget; agent also polls).
    if req.callback_url:
        try:
            httpx.post(req.callback_url, json=resolution.model_dump(mode="json"), timeout=5)
        except Exception:
            pass
    return resolution


@app.get("/resolution/{request_id}", response_model=HumanResolution)
def get_resolution(request_id: str) -> HumanResolution:
    res = STORE.get_resolution(request_id)
    if not res:
        raise HTTPException(status_code=404, detail="not resolved yet")
    return res


@app.get("/pending", response_model=list[RoutingDecision])
def pending() -> list[RoutingDecision]:
    return STORE.pending()
