"""The phone reply page reached from the SMS short link (sivra.io/d/<code>).

A human taps a button to resolve the delegation and rate it — no app, no JS
framework. Approve/Counter/Decline are submit buttons; the 👍/👎 rating rides
along as the reward signal. Both the page and the API share supervisor.service.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from shared.contracts.schema import (
    HumanRating,
    HumanResolution,
    Resolution,
    RoutingDecision,
    TargetPerson,
)
from supervisor import config, service
from supervisor.store import STORE

router = APIRouter()

_TIER_LABEL = {"async": "FYI", "urgent_push": "Urgent", "voice": "Urgent — call"}


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
background:#0f172a;color:#e2e8f0;display:flex;justify-content:center}}
.card{{width:100%;max-width:460px;padding:22px 20px 40px}}
.badge{{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.04em;
padding:4px 10px;border-radius:999px;background:#1e293b;color:#93c5fd}}
.badge.urgent{{background:#7f1d1d;color:#fecaca}}
h1{{font-size:18px;margin:14px 0 4px}}.msg{{font-size:20px;line-height:1.35;margin:10px 0 18px}}
.meta{{color:#94a3b8;font-size:13px;margin-bottom:22px}}
.who{{color:#cbd5e1;font-weight:600}}
button,input{{font:inherit}}
.btn{{display:block;width:100%;padding:16px;margin:10px 0;border:0;border-radius:14px;
font-size:17px;font-weight:700;cursor:pointer}}
.approve{{background:#16a34a;color:#fff}}.decline{{background:#b91c1c;color:#fff}}
.counter{{background:#1e293b;color:#e2e8f0;border:1px solid #334155}}
input[type=number]{{width:100%;padding:14px;border-radius:12px;border:1px solid #334155;
background:#0b1220;color:#e2e8f0;margin:4px 0 2px}}
.rate{{margin-top:26px;border-top:1px solid #1e293b;padding-top:18px}}
.rate p{{color:#94a3b8;font-size:14px;margin:0 0 10px}}
.rk{{display:flex;gap:10px}}.rk button{{flex:1;padding:12px;border-radius:12px;border:1px solid #334155;
background:#0b1220;color:#e2e8f0;font-size:18px;cursor:pointer}}
.ok{{text-align:center;padding:40px 0}}.ok .big{{font-size:46px}}
small{{color:#64748b}}
</style></head><body><div class="card">{body}</div></body></html>"""


def _form(code: str, req, decision: RoutingDecision) -> str:
    urgent = decision.urgency_tier.value != "async"
    who = config.label(req.org_id, decision.target_person)
    price = req.proposed_value or (req.item.listed_price if req.item else None)
    counter_default = int(req.budget_cap or (price or 0))
    return _shell(
        "Decision needed",
        f"""
<span class="badge {'urgent' if urgent else ''}">{_TIER_LABEL.get(decision.urgency_tier.value,'')}</span>
<h1>Buyer agent needs your call</h1>
<div class="msg">{decision.suggested_message}</div>
<div class="meta">for <span class="who">{who}</span> · {req.marketplace} · agent {req.agent_id}<br>
<small>{decision.rationale}</small></div>
<form method="post" action="/d/{code}">
  <button class="btn approve" name="resolution" value="approve">✅ Approve</button>
  <div class="counter">
    <label>Counter at €<input type="number" name="value" value="{counter_default}" inputmode="numeric"></label>
    <button class="btn counter" name="resolution" value="counter" style="margin-top:10px">✏️ Send counter-offer</button>
  </div>
  <button class="btn decline" name="resolution" value="decline">❌ Decline</button>
  <div class="rate">
    <p>Was pinging <b>{who}</b> ({_TIER_LABEL.get(decision.urgency_tier.value,'')}) the right call?</p>
    <div class="rk">
      <button name="rating" value="good" type="submit" formnovalidate>👍 Right</button>
      <button name="rating" value="wrong" type="submit" formnovalidate>👎 Wrong</button>
    </div>
  </div>
</form>""",
    )


def _resolved(decision: RoutingDecision, res: HumanResolution) -> str:
    extra = f" at €{int(res.value)}" if res.value else ""
    rate = {"good": "👍", "wrong": "👎", "partial": "🤷", None: ""}.get(
        res.rating.value if res.rating else None, ""
    )
    return _shell(
        "Done",
        f"""<div class="ok"><div class="big">✅</div>
<h1>{res.resolution.value.capitalize()}{extra}</h1>
<div class="meta">Sent back to the agent. {rate}</div>
<small>The agent is resuming the deal.</small></div>""",
    )


def _lookup(code: str):
    rid = STORE.request_id_for(code)
    if not rid:
        return None, None
    return STORE.requests.get(rid), STORE.decisions.get(rid)


@router.get("/d/{code}", response_class=HTMLResponse)
def reply_page(code: str) -> HTMLResponse:
    req, decision = _lookup(code)
    if not req or not decision:
        return HTMLResponse(_shell("Not found", '<div class="ok"><div class="big">🔍</div><h1>Link expired</h1></div>'), status_code=404)
    existing = STORE.get_resolution(req.request_id)
    if existing:
        return HTMLResponse(_resolved(decision, existing))
    return HTMLResponse(_form(code, req, decision))


@router.post("/d/{code}", response_class=HTMLResponse)
def reply_submit(
    code: str,
    resolution: Optional[str] = Form(None),
    rating: Optional[str] = Form(None),
    value: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
) -> HTMLResponse:
    req, decision = _lookup(code)
    if not req or not decision:
        return HTMLResponse(_shell("Not found", '<div class="ok"><h1>Link expired</h1></div>'), status_code=404)
    existing = STORE.get_resolution(req.request_id)
    if existing:
        return HTMLResponse(_resolved(decision, existing))
    res = HumanResolution(
        request_id=req.request_id,
        resolved_by=decision.target_person.value if decision.target_person != TargetPerson.none else "human",
        resolution=Resolution(resolution) if resolution else Resolution.approve,
        value=value,
        notes=notes,
        rating=HumanRating(rating) if rating else None,
    )
    service.resolve_request(res)
    return HTMLResponse(_resolved(decision, res))
