"""Quartermaster supervisor service.

  POST /escalate            buyer agent submits a DecisionRequest -> RoutingDecision
  POST /resolve/{id}        human (or Telegram callback) submits a HumanResolution
  GET  /resolution/{id}     buyer agent polls for the human's answer
  GET  /pending             open delegations (for a human UI / CLI)
  GET  /health
"""
from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()  # pick up .env before router/delivery read their keys

from shared.contracts.schema import DecisionRequest, HumanResolution, RoutingDecision
from supervisor import dispatch, service
from supervisor.guardrail import extract_guardrail
from supervisor.route import router as route_router
from supervisor.router import get_router
from supervisor.store import STORE
from supervisor.web import router as web_router

app = FastAPI(title="sivra supervisor", version="0.1.0")
app.include_router(web_router)
app.include_router(route_router)  # additive: stateless POST /route (policy-driven)
_router = get_router()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "router": _router.version, "delivery": dispatch.get_delivery().name}


@app.post("/escalate", response_model=RoutingDecision)
def escalate(req: DecisionRequest) -> RoutingDecision:
    guardrail = extract_guardrail(req)
    decision = _router.route(req, guardrail)
    STORE.add(req, decision)
    STORE.register_code(req.request_id)
    if decision.should_delegate:
        dispatch.dispatch(req, decision)
    return decision


@app.post("/resolve/{request_id}", response_model=HumanResolution)
def resolve(request_id: str, resolution: HumanResolution) -> HumanResolution:
    resolution.request_id = request_id
    try:
        return service.resolve_request(resolution)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown request_id")


@app.post("/resolve", response_model=HumanResolution)
def resolve_body(resolution: HumanResolution) -> HumanResolution:
    """Static-path variant: request_id comes from the body, not the URL.

    Webhook tool callers (e.g. the ElevenLabs voice agent) hit a fixed URL and
    carry request_id in the payload, which avoids fragile path templating.
    """
    if not resolution.request_id:
        raise HTTPException(status_code=422, detail="request_id required in body")
    try:
        return service.resolve_request(resolution)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown request_id")


@app.get("/resolution/{request_id}", response_model=HumanResolution)
def get_resolution(request_id: str) -> HumanResolution:
    res = STORE.get_resolution(request_id)
    if not res:
        raise HTTPException(status_code=404, detail="not resolved yet")
    return res


@app.get("/pending", response_model=list[RoutingDecision])
def pending() -> list[RoutingDecision]:
    return STORE.pending()
