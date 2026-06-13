"""Public web surface served at sivra.io:
  GET  /            landing page
  GET  /d/{code}    the phone reply page reached from the SMS short link
  POST /d/{code}    resolve + rate the delegation (no JS, no app)

Design: warm-paper light theme, Inter, restrained ink/indigo palette — meant to
read like a modern AI-lab product, not a toy.
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

_TIER = {"async": "Routine", "urgent_push": "Urgent", "voice": "Urgent · call"}

_CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#F5F4EF;color:#17150F;
font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:inherit}
.mono{font-family:ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace}
.wrap{min-height:100dvh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:28px 20px}
.brand{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:11px;letter-spacing:.22em;
text-transform:uppercase;color:#9A958A;margin-bottom:20px}
.card{width:100%;max-width:480px;background:#FFFFFF;border:1px solid #E8E5DC;border-radius:20px;
padding:30px 28px;box-shadow:0 1px 2px rgba(23,21,15,.03),0 16px 40px -12px rgba(23,21,15,.10)}
.eyebrow{display:flex;align-items:center;gap:9px;font-size:12.5px;font-weight:600;letter-spacing:.02em;
color:#6E6A60;text-transform:uppercase;margin-bottom:18px}
.dot{width:8px;height:8px;border-radius:50%;background:#8C887D;box-shadow:0 0 0 4px rgba(140,136,125,.12)}
.dot.urgent{background:#C2571F;box-shadow:0 0 0 4px rgba(194,87,31,.14)}
.dot.live{background:#3BA776;box-shadow:0 0 0 4px rgba(59,167,118,.16)}
h1.lead{font-size:23px;line-height:1.32;font-weight:600;letter-spacing:-.015em;margin:0 0 14px}
.meta{font-size:14px;color:#6E6A60;margin:0 0 24px}
.meta b{color:#3C392F;font-weight:600}
.rationale{display:block;margin-top:6px;color:#948F84;font-size:13px}
form{margin:0}
fieldset.rate{border:0;padding:0;margin:0 0 22px;display:flex;flex-wrap:wrap;gap:8px}
fieldset.rate legend{font-size:13px;color:#6E6A60;margin-bottom:10px;padding:0}
fieldset.rate input{position:absolute;opacity:0;pointer-events:none}
fieldset.rate label{flex:1;min-width:120px;text-align:center;padding:10px 12px;border:1px solid #E2DFD6;
border-radius:11px;font-size:14px;font-weight:500;color:#54514A;cursor:pointer;background:#FBFAF7;transition:.12s}
fieldset.rate label:hover{border-color:#CFCBC0}
fieldset.rate input:checked+label{border-color:#4F46E5;color:#3730A3;background:#EEEDFC;box-shadow:0 0 0 1px #4F46E5 inset}
.btn{display:block;width:100%;border:0;border-radius:13px;padding:15px;font-size:15.5px;font-weight:600;
font-family:inherit;cursor:pointer;margin:10px 0;transition:.12s;letter-spacing:-.005em}
.btn.primary{background:#17150F;color:#fff}.btn.primary:hover{background:#322e22}
.btn.ghost{background:#fff;color:#17150F;border:1px solid #DEDAD0}.btn.ghost:hover{border-color:#bdb8ac}
.btn.quiet{background:transparent;color:#8A8579;padding:12px;font-weight:500}.btn.quiet:hover{color:#5b5750}
.counter-row{display:flex;gap:10px;align-items:stretch;margin:10px 0}
.field{flex:1;display:flex;align-items:center;border:1px solid #E2DFD6;border-radius:13px;padding:0 14px;background:#FBFAF7}
.field .cur{color:#9A958A;font-size:15px;margin-right:2px}
.field input{border:0;background:transparent;width:100%;padding:14px 6px;font-size:15.5px;font-family:inherit;color:#17150F;outline:none}
.counter-row .btn{width:auto;flex:0 0 auto;margin:0;padding:14px 22px}
.foot{margin-top:24px;padding-top:16px;border-top:1px solid #EFECE4;display:flex;justify-content:space-between;
font-size:12px;color:#A39E92}
.center{text-align:center}
.check{width:54px;height:54px;border-radius:50%;background:#EFEDFC;color:#4F46E5;display:flex;align-items:center;
justify-content:center;margin:8px auto 18px;font-size:26px}
/* landing */
.hero{max-width:660px;text-align:center}
.hero .wordmark{font-size:15px;font-weight:700;letter-spacing:.04em;margin-bottom:30px}
.hero h1{font-size:clamp(28px,6vw,44px);line-height:1.1;font-weight:600;letter-spacing:-.03em;margin:0 0 18px}
.hero .sub{font-size:17px;color:#5C594F;max-width:520px;margin:0 auto 32px}
.steps{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:34px}
.step{flex:1;min-width:150px;max-width:200px;background:#fff;border:1px solid #E8E5DC;border-radius:14px;
padding:16px 14px;text-align:left}
.step .n{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#4F46E5;margin-bottom:7px}
.step .t{font-size:14.5px;font-weight:600;margin-bottom:3px}
.step .d{font-size:13px;color:#807B70}
.status{display:inline-flex;align-items:center;gap:9px;font-size:13px;color:#6E6A60;
border:1px solid #E5E2D9;border-radius:999px;padding:8px 15px;background:#fff}
.pagefoot{margin-top:30px;font-size:12px;color:#A39E92}
"""

_HEAD_OPEN = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="theme-color" content="#F5F4EF"><title>'
)
_HEAD_REST = (
    "</title>"
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">'
    "<style>" + _CSS + "</style></head><body>"
)


def _page(title: str, inner: str, brand: bool = True) -> str:
    top = '<div class="brand">Quartermaster</div>' if brand else ""
    return _HEAD_OPEN + title + _HEAD_REST + f'<div class="wrap">{top}{inner}</div></body></html>'


def _form(code: str, req, decision: RoutingDecision) -> str:
    urgent = decision.urgency_tier.value != "async"
    who = config.label(req.org_id, decision.target_person)
    counter_default = int(req.budget_cap or (req.proposed_value or (req.item.listed_price if req.item else 0)) or 0)
    rationale = f'<span class="rationale">{decision.rationale}</span>' if decision.rationale else ""
    return _page(
        "Decision required · Quartermaster",
        f"""<div class="card">
  <div class="eyebrow"><span class="dot {'urgent' if urgent else ''}"></span>{_TIER.get(decision.urgency_tier.value,'')} · decision required</div>
  <h1 class="lead">{decision.suggested_message}</h1>
  <p class="meta">Requested by buyer agent <b>{req.agent_id}</b> on {req.marketplace}, for <b>{who}</b>.{rationale}</p>
  <form method="post" action="/d/{code}">
    <fieldset class="rate">
      <legend>Was this routed to the right person, at the right urgency?</legend>
      <input type="radio" name="rating" id="r-good" value="good"><label for="r-good">Right call</label>
      <input type="radio" name="rating" id="r-wrong" value="wrong"><label for="r-wrong">Mis-routed</label>
    </fieldset>
    <button class="btn primary" name="resolution" value="approve">Approve</button>
    <div class="counter-row">
      <div class="field"><span class="cur">€</span><input type="number" name="value" value="{counter_default}" inputmode="numeric" aria-label="counter amount"></div>
      <button class="btn ghost" name="resolution" value="counter">Counter</button>
    </div>
    <button class="btn quiet" name="resolution" value="decline">Decline</button>
  </form>
  <div class="foot"><span>Autonomous procurement</span><span class="mono">{req.request_id[:8]}</span></div>
</div>""",
    )


def _resolved(decision: RoutingDecision, res: HumanResolution) -> str:
    extra = f" · €{int(res.value)}" if res.value else ""
    note = {"good": "Marked well-routed.", "wrong": "Marked mis-routed — the router will learn from it.", "partial": ""}.get(
        res.rating.value if res.rating else "", ""
    )
    return _page(
        "Done · Quartermaster",
        f"""<div class="card center">
  <div class="check">✓</div>
  <h1 class="lead">{res.resolution.value.capitalize()}{extra}</h1>
  <p class="meta">Sent back to the agent — it's resuming the deal.{(' ' + note) if note else ''}</p>
  <div class="foot center" style="justify-content:center"><span class="mono">{res.request_id[:8]}</span></div>
</div>""",
    )


def _home() -> str:
    return _page(
        "Quartermaster",
        """<div class="hero">
  <div class="wordmark">Quartermaster</div>
  <h1>The coordination layer for autonomous agents and the people who back them.</h1>
  <p class="sub">Quartermaster runs fleets of buyer agents that find and negotiate real deals — and brings in a human, the right one, at the right urgency, only when it counts.</p>
  <div class="steps">
    <div class="step"><div class="n">01</div><div class="t">Agents act</div><div class="d">Fleets shop, compare, and negotiate across marketplaces.</div></div>
    <div class="step"><div class="n">02</div><div class="t">The supervisor routes</div><div class="d">Escalations reach the right person at the right urgency.</div></div>
    <div class="step"><div class="n">03</div><div class="t">You decide</div><div class="d">One tap to approve, counter, or decline — and it learns.</div></div>
  </div>
  <div class="status"><span class="dot live"></span> System live</div>
  <div class="pagefoot">Quartermaster · autonomous procurement</div>
</div>""",
        brand=False,
    )


def _lookup(code: str):
    rid = STORE.request_id_for(code)
    if not rid:
        return None, None
    return STORE.requests.get(rid), STORE.decisions.get(rid)


_NOTFOUND = '<div class="card center"><div class="check">·</div><h1 class="lead">Link expired</h1><p class="meta">This decision is no longer available.</p></div>'


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(_home())


@router.get("/d/{code}", response_class=HTMLResponse)
def reply_page(code: str) -> HTMLResponse:
    req, decision = _lookup(code)
    if not req or not decision:
        return HTMLResponse(_page("Not found", _NOTFOUND), status_code=404)
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
        return HTMLResponse(_page("Not found", _NOTFOUND), status_code=404)
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
