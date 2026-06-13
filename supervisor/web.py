"""Public web surface served at sivra.io:
  GET  /            landing page
  GET  /d/{code}    the phone reply page reached from the SMS short link
  POST /d/{code}    resolve + rate the delegation (no JS, no app)

Design: warm-paper light theme, Fraunces (display serif) + Inter, near-monochrome
with a single restrained accent.
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

_MARK = (
    '<svg class="mark" width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">'
    '<circle cx="11" cy="11" r="9.2" stroke="currentColor" stroke-width="1.1" opacity=".45"/>'
    '<circle cx="11" cy="11" r="2.6" fill="currentColor"/>'
    '<circle cx="19.4" cy="11" r="1.9" fill="currentColor"/></svg>'
)

_CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
:root{--paper:#F4F2EB;--card:#FBFAF5;--ink:#1B1A15;--muted:#615D52;--faint:#A39E8E;
--line:#E5E1D5;--line2:#EFEBE0;--accent:#3A357C;--warm:#A6592B;
--serif:'Fraunces',Georgia,serif;--sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
--mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.mono{font-family:var(--mono)}
.brand{display:inline-flex;align-items:center;gap:8px;color:var(--ink);text-decoration:none}
.brand .mark{color:var(--accent)}
.brand .wm{font-family:var(--serif);font-size:20px;font-weight:500;letter-spacing:-.01em}
/* shared centered layout (reply pages) */
.wrap{min-height:100dvh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:30px 20px;
position:relative}
.wrap>.brand{margin-bottom:26px}
.wrap::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
background:radial-gradient(120% 80% at 50% -10%,rgba(58,53,124,.06),transparent 60%)}
/* reply card */
.card{width:100%;max-width:486px;background:var(--card);border:1px solid var(--line);border-radius:22px;
padding:32px 30px;box-shadow:0 1px 1px rgba(27,26,21,.03),0 24px 56px -20px rgba(27,26,21,.16)}
.eyebrow{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:11px;letter-spacing:.16em;
text-transform:uppercase;color:var(--muted);margin-bottom:20px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--faint)}.dot.urgent{background:var(--warm)}
h1.lead{font-family:var(--serif);font-weight:400;font-size:26px;line-height:1.28;letter-spacing:-.01em;margin:0 0 16px}
.meta{font-size:14px;color:var(--muted);margin:0 0 26px}.meta b{color:#403C31;font-weight:600}
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
font-family:inherit;cursor:pointer;margin:11px 0;transition:.13s}
.btn.primary{background:var(--ink);color:#FBFAF5}.btn.primary:hover{background:#34322a}
.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}.btn.ghost:hover{border-color:#c8c2b2}
.btn.quiet{background:transparent;color:var(--faint);padding:12px;font-weight:500}.btn.quiet:hover{color:var(--muted)}
.counter-row{display:flex;gap:10px;margin:11px 0}
.field{flex:1;display:flex;align-items:center;border:1px solid var(--line);border-radius:13px;padding:0 14px;background:#fff}
.field .cur{color:var(--faint);font-size:15px}
.field input{border:0;background:transparent;width:100%;padding:14px 6px;font-size:15px;font-family:inherit;color:var(--ink);outline:none}
.counter-row .btn{width:auto;margin:0;padding:14px 22px}
.foot{margin-top:26px;padding-top:17px;border-top:1px solid var(--line2);display:flex;justify-content:space-between;
font-size:11.5px;color:var(--faint)}
.center{text-align:center}
.check{width:52px;height:52px;border-radius:50%;border:1px solid rgba(58,53,124,.25);color:var(--accent);
display:flex;align-items:center;justify-content:center;margin:6px auto 20px;font-size:22px}
/* landing */
.page{max-width:760px;margin:0 auto;padding:0 24px 72px}
.top{display:flex;align-items:center;justify-content:space-between;padding:26px 0 22px;margin-bottom:54px;border-bottom:1px solid var(--line)}
.top .tag{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--faint)}
.hero{margin-bottom:72px}
.hero h1{font-family:var(--serif);font-weight:400;font-size:clamp(30px,5.2vw,46px);line-height:1.1;
letter-spacing:-.02em;margin:0 0 24px}
.hero h1 em{font-style:italic;color:var(--accent)}
.hero p{font-size:18px;color:var(--muted);max-width:60ch;line-height:1.62;margin:0}
.sec{margin-bottom:66px}
.sec-label{font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);margin-bottom:12px}
.sec h2{font-family:var(--serif);font-weight:400;font-size:27px;letter-spacing:-.01em;margin:0 0 28px}
/* run timeline */
.tl{border-left:1px solid var(--line);margin-left:5px}
.tl-item{position:relative;padding:0 0 26px 26px}
.tl-item:last-child{padding-bottom:0}
.tl-item::before{content:"";position:absolute;left:-5.5px;top:5px;width:10px;height:10px;border-radius:50%;
background:var(--paper);border:1.5px solid var(--accent)}
.tl-item .lab{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
.tl-item p{margin:5px 0 0;font-size:15.5px;color:#39362D;line-height:1.6}
.tl-item p b{color:var(--ink);font-weight:600}
.sms{margin-top:13px;background:#fff;border:1px solid var(--line);border-radius:4px 14px 14px 14px;
padding:13px 16px;max-width:430px;box-shadow:0 1px 1px rgba(27,26,21,.04)}
.sms .who{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);display:block;margin-bottom:5px}
.sms .body{font-size:14.5px;color:var(--ink);line-height:1.5}
.sms .lk{color:var(--accent);text-decoration:none}
/* how */
.point{display:grid;grid-template-columns:34px 1fr;gap:14px;padding:24px 0;border-top:1px solid var(--line)}
.point:last-child{border-bottom:1px solid var(--line)}
.point .pn{font-family:var(--mono);font-size:12px;color:var(--accent);padding-top:3px}
.point .pt{font-family:var(--serif);font-size:19px;font-weight:500;margin:0 0 7px;letter-spacing:-.005em}
.point .pd{font-size:15px;color:var(--muted);line-height:1.62;margin:0}
.site-foot{margin-top:18px;padding-top:24px;border-top:1px solid var(--line);font-family:var(--mono);
font-size:11px;letter-spacing:.06em;color:var(--faint);display:flex;justify-content:space-between}
@media(max-width:560px){.hero p{font-size:16.5px}.top{margin-bottom:40px}}
"""

_HEAD_OPEN = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="theme-color" content="#F4F2EB"><title>'
)
_HEAD_REST = (
    "</title>"
    '<meta name="description" content="sivra runs fleets of autonomous buying agents that shop, negotiate, and close deals — and brings a human in only when a real decision needs one.">'
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">'
    "<style>" + _CSS + "</style></head><body>"
)

_BRAND = f'<a class="brand" href="/">{_MARK}<span class="wm">sivra</span></a>'


def _page(title: str, inner: str, brand: bool = True, layout: str = "center") -> str:
    if layout == "page":
        return _HEAD_OPEN + title + _HEAD_REST + f'<div class="page">{inner}</div></body></html>'
    top = _BRAND if brand else ""
    return _HEAD_OPEN + title + _HEAD_REST + f'<div class="wrap">{top}{inner}</div></body></html>'


def _home() -> str:
    inner = f"""
<header class="top">{_BRAND}<span class="tag">Autonomous procurement</span></header>

<section class="hero">
  <h1>Agents that shop, negotiate, and buy for you. You only hear about the decisions that <em>actually</em> need a person.</h1>
  <p>Tell sivra what you're after. It runs dozens of buying agents across marketplaces at once — filtering listings, messaging sellers, talking price — and runs the whole errand to the finish. When something genuinely needs you, it reaches the right person on the right channel, with everything they need to decide in a single tap.</p>
</section>

<section class="sec">
  <div class="sec-label">Example · one run, start to finish</div>
  <h2>What a run looks like</h2>
  <div class="tl">
    <div class="tl-item"><span class="lab">The request</span><p>&ldquo;Used road bike, 56&nbsp;cm, under €400 — pickup in Munich this week.&rdquo;</p></div>
    <div class="tl-item"><span class="lab">Dispatch</span><p>sivra spins up <b>24 agents</b> across three marketplaces. Each drives its site by sight — searching, filtering by frame size, opening listings, and messaging sellers — all in parallel.</p></div>
    <div class="tl-item"><span class="lab">Shortlist</span><p>Within minutes they've worked the field down to three real candidates, and talked one seller from <b>€420 down to €385</b>.</p></div>
    <div class="tl-item"><span class="lab">Escalation</span><p>One thing isn't sivra's call: pickup is Saturday 8&nbsp;pm in Wedding, outside your usual area. Not urgent — so it texts rather than calls.</p>
      <div class="sms"><span class="who">sivra → you</span><span class="body">Specialized Allez 56&nbsp;cm for €385. Pickup Sat 8&nbsp;pm, Wedding — outside your usual area. Approve, counter, or decline?<br><span class="lk">sivra.io/d/6a2703</span></span></div></div>
    <div class="tl-item"><span class="lab">Decision</span><p>You tap <b>Approve</b>. The agent confirms the handover with the seller and closes the deal. Time you spent: about eight seconds.</p></div>
  </div>
</section>

<section class="sec">
  <div class="sec-label">How it works</div>
  <h2>Four ideas, one system</h2>
  <div class="point"><div class="pn">01</div><div><p class="pt">Small agents, run wide</p><p class="pd">Each agent is a compact model fine-tuned to operate one marketplace by sight. Because they're small, sivra runs a hundred in parallel for the cost of a single frontier query — searching the whole market at once instead of one query at a time.</p></div></div>
  <div class="point"><div class="pn">02</div><div><p class="pt">Escalation, not interruption</p><p class="pd">Most steps never reach you. sivra decides what genuinely needs a human and routes it — a quiet text for a routine confirmation, an urgent ping when a deal's about to slip, a phone call when it's complex — and to the right person, whether that's you, procurement, or a manager.</p></div></div>
  <div class="point"><div class="pn">03</div><div><p class="pt">Decide from your phone, no app</p><p class="pd">Escalations arrive as a text with a link: approve, counter, or decline in one tap. For the urgent tier, sivra calls and talks the decision through with you, then carries out what you choose.</p></div></div>
  <div class="point"><div class="pn">04</div><div><p class="pt">It compounds</p><p class="pd">sivra sharpens with every run. The agents learn from whether a purchase actually went through; the router learns who you'd really want pinged, and how loudly, from the calls you make. Next week's system is better than today's.</p></div></div>
</section>

<footer class="site-foot"><span>sivra — autonomous procurement, supervised</span><span>sivra.io</span></footer>
"""
    return _page("sivra — autonomous procurement, supervised", inner, layout="page")


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
