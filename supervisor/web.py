"""Public web surface served at sivra.io:
  GET  /            landing page
  GET  /d/{code}    the phone reply page reached from the SMS short link
  POST /d/{code}    resolve + rate the delegation (no JS, no app)

Design: warm-paper light theme, Fraunces (display serif) + Inter, near-monochrome
with a single restrained accent. Reads like a considered AI-lab product.
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

_TIER = {"async": "Routine", "urgent_push": "Time-sensitive", "voice": "Urgent · call"}

# minimal logo mark: an orbit — one supervisor node, a satellite agent
_MARK = (
    '<svg class="mark" width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">'
    '<circle cx="11" cy="11" r="9.2" stroke="currentColor" stroke-width="1.1" opacity=".45"/>'
    '<circle cx="11" cy="11" r="2.6" fill="currentColor"/>'
    '<circle cx="19.4" cy="11" r="1.9" fill="currentColor"/></svg>'
)

_CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
:root{--paper:#F4F2EB;--card:#FBFAF5;--ink:#1B1A15;--muted:#6B6759;--faint:#A39E8E;
--line:#E5E1D5;--line2:#EFEBE0;--accent:#3A357C;--warm:#A6592B;
--serif:'Fraunces',Georgia,'Times New Roman',serif;--sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
--mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
background:radial-gradient(120% 80% at 50% -10%,rgba(58,53,124,.06),transparent 60%)}
.wrap{position:relative;z-index:1;min-height:100dvh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:30px 20px}
.mono{font-family:var(--mono)}
.brand{display:inline-flex;align-items:center;gap:8px;color:var(--ink);margin-bottom:26px;text-decoration:none}
.brand .mark{color:var(--accent)}
.brand .wm{font-family:var(--serif);font-size:21px;font-weight:500;letter-spacing:-.01em}
.eyebrow{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:11px;letter-spacing:.16em;
text-transform:uppercase;color:var(--muted);margin-bottom:20px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--faint);box-shadow:0 0 0 4px rgba(163,158,142,.14)}
.dot.urgent{background:var(--warm);box-shadow:0 0 0 4px rgba(166,89,43,.16)}
.dot.live{background:#3F9E74;box-shadow:0 0 0 4px rgba(63,158,116,.16)}
/* card / reply */
.card{width:100%;max-width:486px;background:var(--card);border:1px solid var(--line);border-radius:22px;
padding:32px 30px;box-shadow:0 1px 1px rgba(27,26,21,.03),0 24px 56px -20px rgba(27,26,21,.16)}
h1.lead{font-family:var(--serif);font-weight:400;font-size:26px;line-height:1.28;letter-spacing:-.01em;margin:0 0 16px}
.meta{font-size:14px;color:var(--muted);margin:0 0 26px}
.meta b{color:#403C31;font-weight:600}
.rationale{display:block;margin-top:7px;color:var(--faint);font-size:12.5px}
form{margin:0}
fieldset.rate{border:0;padding:0;margin:0 0 24px}
fieldset.rate legend{font-size:13px;color:var(--muted);margin-bottom:11px;padding:0}
.pills{display:flex;gap:9px}
fieldset.rate input{position:absolute;opacity:0;pointer-events:none}
fieldset.rate label{flex:1;text-align:center;padding:11px 12px;border:1px solid var(--line);border-radius:12px;
font-size:14px;font-weight:500;color:#5B5749;cursor:pointer;background:#fff;transition:.13s}
fieldset.rate label:hover{border-color:#CFCABA}
fieldset.rate input:checked+label{border-color:var(--accent);color:var(--accent);
background:rgba(58,53,124,.05);box-shadow:0 0 0 1px var(--accent) inset}
.btn{display:block;width:100%;border:0;border-radius:13px;padding:15px;font-size:15px;font-weight:600;
font-family:inherit;cursor:pointer;margin:11px 0;transition:.13s;letter-spacing:-.003em}
.btn.primary{background:var(--ink);color:#FBFAF5}.btn.primary:hover{background:#34322a}
.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}.btn.ghost:hover{border-color:#c8c2b2}
.btn.quiet{background:transparent;color:var(--faint);padding:12px;font-weight:500}.btn.quiet:hover{color:var(--muted)}
.counter-row{display:flex;gap:10px;margin:11px 0}
.field{flex:1;display:flex;align-items:center;border:1px solid var(--line);border-radius:13px;padding:0 14px;background:#fff}
.field .cur{color:var(--faint);font-size:15px}
.field input{border:0;background:transparent;width:100%;padding:14px 6px;font-size:15px;font-family:inherit;color:var(--ink);outline:none}
.counter-row .btn{width:auto;margin:0;padding:14px 22px}
.foot{margin-top:26px;padding-top:17px;border-top:1px solid var(--line2);display:flex;justify-content:space-between;
font-size:11.5px;color:var(--faint);letter-spacing:.01em}
.center{text-align:center}
.check{width:52px;height:52px;border-radius:50%;border:1px solid rgba(58,53,124,.25);color:var(--accent);
display:flex;align-items:center;justify-content:center;margin:6px auto 20px;font-size:22px}
/* landing */
.hero{max-width:720px;text-align:center}
.hero h1{font-family:var(--serif);font-weight:400;font-size:clamp(32px,6.4vw,52px);line-height:1.06;
letter-spacing:-.02em;margin:0 0 20px}
.hero h1 em{font-style:italic;color:var(--accent)}
.hero .sub{font-size:17px;color:var(--muted);max-width:540px;margin:0 auto 40px;line-height:1.55}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:0;text-align:left;border-top:1px solid var(--line);margin-bottom:38px}
.step{padding:20px 18px 4px;border-right:1px solid var(--line)}
.step:last-child{border-right:0}
.step .n{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.12em;margin-bottom:9px}
.step .t{font-family:var(--serif);font-size:18px;font-weight:500;margin-bottom:5px}
.step .d{font-size:13px;color:var(--muted);line-height:1.5}
.status{display:inline-flex;align-items:center;gap:9px;font-size:12.5px;color:var(--muted);font-family:var(--mono);
letter-spacing:.04em;border:1px solid var(--line);border-radius:999px;padding:8px 16px;background:var(--card)}
.pagefoot{margin-top:30px;font-family:var(--mono);font-size:11px;color:var(--faint);letter-spacing:.08em}
@media(max-width:560px){.steps{grid-template-columns:1fr;border-top:0}.step{border-right:0;border-top:1px solid var(--line);padding:18px 2px 14px}}
"""

_HEAD_OPEN = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="theme-color" content="#F4F2EB"><title>'
)
_HEAD_REST = (
    "</title>"
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">'
    "<style>" + _CSS + "</style></head><body>"
)

_BRAND = f'<a class="brand" href="/">{_MARK}<span class="wm">sivra</span></a>'


def _page(title: str, inner: str, brand: bool = True) -> str:
    top = _BRAND if brand else ""
    return _HEAD_OPEN + title + _HEAD_REST + f'<div class="wrap">{top}{inner}</div></body></html>'


def _form(code: str, req, decision: RoutingDecision) -> str:
    urgent = decision.urgency_tier.value != "async"
    who = config.label(req.org_id, decision.target_person)
    counter_default = int(req.budget_cap or (req.proposed_value or (req.item.listed_price if req.item else 0)) or 0)
    rationale = f'<span class="rationale">{decision.rationale}</span>' if decision.rationale else ""
    return _page(
        "Decision required · sivra",
        f"""<div class="card">
  <div class="eyebrow"><span class="dot {'urgent' if urgent else ''}"></span>{_TIER.get(decision.urgency_tier.value,'')} · decision required</div>
  <h1 class="lead">{decision.suggested_message}</h1>
  <p class="meta">Raised by buyer agent <b>{req.agent_id}</b> on {req.marketplace}, routed to <b>{who}</b>.{rationale}</p>
  <form method="post" action="/d/{code}">
    <fieldset class="rate">
      <legend>Was this routed to the right person, at the right urgency?</legend>
      <div class="pills">
        <input type="radio" name="rating" id="r-good" value="good"><label for="r-good">Right call</label>
        <input type="radio" name="rating" id="r-wrong" value="wrong"><label for="r-wrong">Mis-routed</label>
      </div>
    </fieldset>
    <button class="btn primary" name="resolution" value="approve">Approve</button>
    <div class="counter-row">
      <div class="field"><span class="cur">€</span><input type="number" name="value" value="{counter_default}" inputmode="numeric" aria-label="counter amount"></div>
      <button class="btn ghost" name="resolution" value="counter">Counter</button>
    </div>
    <button class="btn quiet" name="resolution" value="decline">Decline</button>
  </form>
  <div class="foot"><span>sivra · autonomous procurement</span><span class="mono">{req.request_id[:8]}</span></div>
</div>""",
    )


def _resolved(decision: RoutingDecision, res: HumanResolution) -> str:
    extra = f" · €{int(res.value)}" if res.value else ""
    note = {"good": "Logged as well-routed.", "wrong": "Logged as mis-routed — the router learns from it.", "partial": ""}.get(
        res.rating.value if res.rating else "", ""
    )
    return _page(
        "Done · sivra",
        f"""<div class="card center">
  <div class="check">✓</div>
  <h1 class="lead">{res.resolution.value.capitalize()}{extra}</h1>
  <p class="meta">Sent back to the agent — it's resuming the deal.{(' ' + note) if note else ''}</p>
  <div class="foot center" style="justify-content:center"><span class="mono">{res.request_id[:8]}</span></div>
</div>""",
    )


def _home() -> str:
    return _page(
        "sivra — supervised autonomous procurement",
        """<div class="hero">
  <div class="eyebrow" style="justify-content:center"><span class="dot live"></span>Autonomous procurement, supervised</div>
  <h1>A coordination layer for autonomous agents — and the <em>people</em> who back them.</h1>
  <p class="sub">sivra runs fleets of buyer agents that find and negotiate real deals, and brings in a human — the right one, at the right urgency — only when it counts.</p>
  <div class="steps">
    <div class="step"><div class="n">01 / ACT</div><div class="t">Agents act</div><div class="d">Fleets search, compare, and negotiate across marketplaces.</div></div>
    <div class="step"><div class="n">02 / ROUTE</div><div class="t">sivra routes</div><div class="d">Each escalation reaches the right person at the right urgency.</div></div>
    <div class="step"><div class="n">03 / DECIDE</div><div class="t">You decide</div><div class="d">One tap to approve, counter, or decline — and it learns.</div></div>
  </div>
  <div class="status"><span class="dot live"></span>system live</div>
  <div class="pagefoot">sivra.io</div>
</div>""",
        brand=True,
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
