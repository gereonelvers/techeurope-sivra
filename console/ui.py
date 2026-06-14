"""HTML for the sivra console page.

Design language lifted from supervisor/web.py so the console looks like part of
sivra: warm-paper #F4F2EB, Fraunces display serif + Inter, --accent #3A357C,
hairline borders, the ink/ghost button styles. Wordmark: "sivra · console".
Single page, no framework — vanilla fetch() against this service's /api/* proxy.
"""
from __future__ import annotations

import json

_MARK = (
    '<svg class="mark" width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">'
    '<circle cx="11" cy="11" r="9.2" stroke="currentColor" stroke-width="1.1" opacity=".45"/>'
    '<circle cx="11" cy="11" r="2.6" fill="currentColor"/>'
    '<circle cx="19.4" cy="11" r="1.9" fill="currentColor"/></svg>'
)

_CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
:root{--paper:#F4F2EB;--card:#FBFAF5;--ink:#1B1A15;--muted:#615D52;--faint:#A39E8E;
--line:#E5E1D5;--line2:#EFEBE0;--accent:#3A357C;--warm:#A6592B;--good:#3F6B43;--bad:#9B3B2F;
--serif:'Fraunces',Georgia,serif;--sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
--mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
background:radial-gradient(120% 70% at 50% -10%,rgba(58,53,124,.06),transparent 60%)}
.mono{font-family:var(--mono)}
a{color:var(--accent)}
.brand{display:inline-flex;align-items:center;gap:8px;color:var(--ink);text-decoration:none}
.brand .mark{color:var(--accent)}
.brand .wm{font-family:var(--serif);font-size:20px;font-weight:500;letter-spacing:-.01em}
.brand .wm .sub{color:var(--muted);font-weight:400}
.page{max-width:880px;margin:0 auto;padding:0 24px 80px}
.top{display:flex;align-items:center;justify-content:space-between;padding:26px 0 22px;margin-bottom:30px;border-bottom:1px solid var(--line)}
.top .tag{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--faint)}
.intro{font-size:15.5px;color:var(--muted);max-width:64ch;margin:0 0 36px;line-height:1.62}
.intro code{font-family:var(--mono);font-size:12.5px;background:#fff;border:1px solid var(--line);border-radius:5px;padding:1px 5px;color:#39362D}
/* tool card */
.tool{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px 24px 22px;margin-bottom:22px;
box-shadow:0 1px 1px rgba(27,26,21,.03),0 18px 44px -28px rgba(27,26,21,.18)}
.tool-head{display:flex;align-items:baseline;gap:10px;margin-bottom:5px}
.tool-n{font-family:var(--mono);font-size:12px;color:var(--accent)}
.tool h2{font-family:var(--serif);font-weight:500;font-size:21px;letter-spacing:-.005em;margin:0}
.tool .desc{font-size:14px;color:var(--muted);margin:0 0 18px;line-height:1.55}
/* preset chips */
.presets{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
.chip{font-family:var(--sans);font-size:13px;font-weight:500;color:#5B5749;background:#fff;border:1px solid var(--line);
border-radius:999px;padding:8px 14px;cursor:pointer;transition:.13s}
.chip:hover{border-color:#CFCABA}
.chip.on{border-color:var(--accent);color:var(--accent);background:rgba(58,53,124,.05);box-shadow:0 0 0 1px var(--accent) inset}
/* form grid */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 14px}
.grid .full{grid-column:1 / -1}
label.fl{display:block;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:0 0 6px;font-family:var(--mono);font-size:10.5px}
input,select,textarea{width:100%;border:1px solid var(--line);border-radius:11px;padding:11px 13px;font-size:14.5px;
font-family:inherit;color:var(--ink);background:#fff;outline:none;transition:.13s}
input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
textarea{resize:vertical;min-height:62px;line-height:1.5}
select{appearance:none;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path d='M2 4l4 4 4-4' stroke='%23A39E8E' stroke-width='1.3' fill='none'/></svg>");
background-repeat:no-repeat;background-position:right 12px center}
.row{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:4px}
.row .grow{flex:1;min-width:180px}
.actions{display:flex;align-items:center;gap:14px;margin-top:16px;flex-wrap:wrap}
.btn{border:0;border-radius:12px;padding:13px 22px;font-size:14.5px;font-weight:600;font-family:inherit;cursor:pointer;transition:.13s;white-space:nowrap}
.btn.primary{background:var(--ink);color:#FBFAF5}.btn.primary:hover{background:#34322a}
.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}.btn.ghost:hover{border-color:#c8c2b2}
.btn[disabled]{opacity:.5;cursor:default}
.hint{font-size:12.5px;color:var(--faint)}
/* result panel */
.result{margin-top:18px;border-top:1px solid var(--line2);padding-top:16px;display:none}
.result.show{display:block}
.status{display:flex;align-items:center;gap:9px;font-size:14px;font-weight:600;margin-bottom:12px}
.status .dot{width:8px;height:8px;border-radius:50%;background:var(--faint)}
.status.ok .dot{background:var(--good)}.status.ok{color:var(--good)}
.status.err .dot{background:var(--bad)}.status.err{color:var(--bad)}
.status.run .dot{background:var(--accent);animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
.kv{font-size:14px;color:#39362D;margin:0 0 8px}.kv b{color:var(--ink);font-weight:600}
.link{display:inline-block;font-family:var(--mono);font-size:13px;background:#fff;border:1px solid var(--line);
border-radius:8px;padding:7px 11px;color:var(--accent);text-decoration:none;margin:2px 0 10px;word-break:break-all}
.link:hover{border-color:var(--accent)}
details{margin-top:6px}
summary{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);cursor:pointer;user-select:none}
summary:hover{color:var(--muted)}
pre{font-family:var(--mono);font-size:12px;line-height:1.55;background:#FCFBF6;border:1px solid var(--line);border-radius:10px;
padding:13px 15px;overflow:auto;margin:10px 0 0;color:#39362D;max-height:300px}
/* pending list */
.pend{display:flex;flex-direction:column;gap:10px;margin-top:4px}
.pend-item{background:#fff;border:1px solid var(--line);border-radius:12px;padding:13px 15px}
.pend-item .pm{font-size:14px;color:var(--ink);margin:0 0 6px;line-height:1.45}
.pend-meta{display:flex;flex-wrap:wrap;gap:8px;font-family:var(--mono);font-size:11px;color:var(--faint)}
.pill{border:1px solid var(--line);border-radius:6px;padding:2px 7px;color:var(--muted)}
.pill.voice{border-color:rgba(166,89,43,.4);color:var(--warm)}
.pill.urgent_push{border-color:rgba(166,89,43,.3);color:var(--warm)}
.site-foot{margin-top:36px;padding-top:22px;border-top:1px solid var(--line);font-family:var(--mono);
font-size:11px;letter-spacing:.06em;color:var(--faint);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:620px){.grid{grid-template-columns:1fr}.page{padding:0 18px 60px}}
"""

_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="theme-color" content="#F4F2EB"><title>sivra · console</title>'
    '<meta name="robots" content="noindex">'
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">'
    "<style>" + _CSS + "</style></head><body>"
)

# Preset SMS-delegation scenarios. Each maps to DecisionRequest-ish fields the
# escalate form posts. Chosen so the router picks a few different people/tiers.
_PRESETS = [
    {
        "key": "laptop",
        "label": "Over-budget laptop",
        "decision_type": "price_over_budget",
        "title": 'Refurbished ThinkPad X1 Carbon',
        "listed_price": 540,
        "proposed_value": 540,
        "budget_cap": 480,
        "agent_confidence": 0.5,
        "situation_text": "Seller won't go below €540 on the ThinkPad — €60 over your €480 cap. Approve, counter, or decline?",
    },
    {
        "key": "pickup",
        "label": "Pickup confirmation",
        "decision_type": "pickup_logistics",
        "title": 'Herman Miller Aeron chair',
        "listed_price": 310,
        "proposed_value": 310,
        "budget_cap": 350,
        "agent_confidence": 0.7,
        "situation_text": "Seller can only do pickup Saturday 8pm in Wedding — outside your usual area. Confirm the pickup window?",
    },
    {
        "key": "safety",
        "label": "Safety flag",
        "decision_type": "safety_flag",
        "title": 'Used MacBook Pro 14"',
        "listed_price": 1450,
        "proposed_value": 1450,
        "budget_cap": 1200,
        "agent_confidence": 0.25,
        "situation_text": "Seller is pushing an off-platform cash handover tonight and the photos don't match the model. Needs a person to sign off before we proceed.",
    },
]


def render_page(*, supervisor_url: str, voice_url: str, demo_phone: str, alpha_sender: str) -> str:
    presets_json = json.dumps(_PRESETS)
    brand = (
        f'<a class="brand" href="/">{_MARK}<span class="wm">sivra <span class="sub">· console</span></span></a>'
    )
    demo_masked = demo_phone or "(QM_DEMO_PHONE unset)"

    body = f"""
<div class="page">
  <header class="top">{brand}<span class="tag">Live tier console · internal</span></header>

  <p class="intro">
    A scratchpad for the live <b>SMS</b> and <b>voice</b> escalation tiers. Buttons here hit the deployed
    supervisor at <code>{supervisor_url}</code> and the voice bridge at <code>{voice_url}</code>.
    Real messages and calls go to <code>{demo_masked}</code> by default — these are <b>live</b>, use sparingly.
  </p>

  <!-- 1 · SMS delegation -->
  <section class="tool" id="t-escalate">
    <div class="tool-head"><span class="tool-n">01</span><h2>Send an SMS delegation</h2></div>
    <p class="desc">POST a DecisionRequest to <code>/escalate</code>. The supervisor routes it (person + urgency),
      texts the demo phone an SMS with a reply link, and returns the routing decision.</p>
    <div class="presets" id="esc-presets"></div>
    <div class="grid">
      <div class="full"><label class="fl">Situation</label><textarea id="esc-situation"></textarea></div>
      <div><label class="fl">Decision type</label>
        <select id="esc-type">
          <option value="price_over_budget">price_over_budget</option>
          <option value="pickup_logistics">pickup_logistics</option>
          <option value="ambiguous_listing">ambiguous_listing</option>
          <option value="approve_purchase">approve_purchase</option>
          <option value="safety_flag">safety_flag</option>
        </select></div>
      <div><label class="fl">Item title</label><input id="esc-title" placeholder="e.g. ThinkPad X1"></div>
      <div><label class="fl">Listed price (€)</label><input id="esc-listed" type="number" step="any" placeholder="540"></div>
      <div><label class="fl">Proposed value (€)</label><input id="esc-proposed" type="number" step="any" placeholder="540"></div>
      <div><label class="fl">Budget cap (€)</label><input id="esc-budget" type="number" step="any" placeholder="480"></div>
      <div><label class="fl">Agent confidence (0–1)</label><input id="esc-conf" type="number" step="0.05" min="0" max="1" value="0.5"></div>
    </div>
    <div class="actions">
      <button class="btn primary" onclick="sendEscalate(this)">Route &amp; send SMS</button>
      <span class="hint">Sends a real SMS to {demo_masked} when the router decides to delegate.</span>
    </div>
    <div class="result" id="esc-result"></div>
  </section>

  <!-- 2 · Voice call -->
  <section class="tool" id="t-call">
    <div class="tool-head"><span class="tool-n">02</span><h2>Place a voice call</h2></div>
    <p class="desc">Runs the escalate&rarr;<code>/call</code> flow: first creates a voice-tier delegation so the
      bridge has a real <code>request_id</code>, then dials via the voice service. Gemini Live talks the decision through.</p>
    <div class="grid">
      <div><label class="fl">Call (E.164)</label><input id="call-to" value="{demo_phone}" placeholder="+49…"></div>
      <div><label class="fl">Addressed as</label><input id="call-person" value="the procurement lead"></div>
      <div class="full"><label class="fl">Context / brief (optional — overrides the scenario)</label>
        <textarea id="call-context" placeholder="Leave blank to use a built-in safety-flag scenario"></textarea></div>
    </div>
    <div class="actions">
      <button class="btn primary" onclick="placeCall(this)">Place call</button>
      <span class="hint">Places a real phone call. Keep it short.</span>
    </div>
    <div class="result" id="call-result"></div>
  </section>

  <!-- 3 · Raw SMS -->
  <section class="tool" id="t-raw">
    <div class="tool-head"><span class="tool-n">03</span><h2>Raw SMS</h2></div>
    <p class="desc">Send an arbitrary text straight through Telnyx (sender <code>{alpha_sender or "—"}</code>). A quick smoke tool — bypasses the supervisor entirely.</p>
    <div class="row">
      <div class="grow"><label class="fl">To (E.164)</label><input id="raw-to" value="{demo_phone}" placeholder="+49…"></div>
    </div>
    <div class="row" style="margin-top:12px">
      <div class="grow" style="flex:1 1 100%"><label class="fl">Message</label>
        <textarea id="raw-text" placeholder="ping from sivra console">ping from sivra console — {alpha_sender or "test"}</textarea></div>
    </div>
    <div class="actions">
      <button class="btn primary" onclick="sendRaw(this)">Send text</button>
      <span class="hint">Goes directly to the number you type.</span>
    </div>
    <div class="result" id="raw-result"></div>
  </section>

  <!-- 4 · Pending -->
  <section class="tool" id="t-pending">
    <div class="tool-head"><span class="tool-n">04</span><h2>Recent delegations</h2></div>
    <p class="desc">Open delegations from <code>/pending</code> — what's currently waiting on a human.</p>
    <div class="actions" style="margin-top:0">
      <button class="btn ghost" id="pend-btn" onclick="loadPending(this)">Refresh</button>
      <span class="hint">Reads {supervisor_url}/pending.</span>
    </div>
    <div class="result" id="pend-result"></div>
  </section>

  <footer class="site-foot"><span>sivra · console — internal tier tester</span><span>{supervisor_url}</span></footer>
</div>

<script>
const PRESETS = {presets_json};

// ── result rendering helpers ────────────────────────────────────────────────
function el(id){{ return document.getElementById(id); }}
function setRunning(panel, label){{
  panel.classList.add('show');
  panel.innerHTML = '<div class="status run"><span class="dot"></span>'+label+'</div>';
}}
function statusBar(ok, label){{
  return '<div class="status '+(ok?'ok':'err')+'"><span class="dot"></span>'+label+'</div>';
}}
function jsonBlock(obj, label){{
  return '<details><summary>'+(label||'Raw JSON')+'</summary><pre>'+
    escapeHtml(JSON.stringify(obj, null, 2))+'</pre></details>';
}}
function escapeHtml(s){{ return s.replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
async function postJSON(url, payload){{
  const r = await fetch(url, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(payload)}});
  let body; try{{ body = await r.json(); }}catch(e){{ body = {{error:'non-JSON response', status:r.status}}; }}
  return {{ httpOk:r.ok, status:r.status, body }};
}}

// ── 1 · escalate ────────────────────────────────────────────────────────────
function applyPreset(p){{
  el('esc-situation').value = p.situation_text;
  el('esc-type').value = p.decision_type;
  el('esc-title').value = p.title || '';
  el('esc-listed').value = p.listed_price ?? '';
  el('esc-proposed').value = p.proposed_value ?? '';
  el('esc-budget').value = p.budget_cap ?? '';
  el('esc-conf').value = p.agent_confidence ?? 0.5;
}}
(function initPresets(){{
  const box = el('esc-presets');
  PRESETS.forEach((p, i) => {{
    const b = document.createElement('button');
    b.className = 'chip' + (i===0 ? ' on' : '');
    b.textContent = p.label;
    b.onclick = () => {{
      [...box.children].forEach(c => c.classList.remove('on'));
      b.classList.add('on'); applyPreset(p);
    }};
    box.appendChild(b);
  }});
  applyPreset(PRESETS[0]);
}})();

async function sendEscalate(btn){{
  const panel = el('esc-result'); btn.disabled = true; setRunning(panel, 'Routing…');
  const payload = {{
    decision_type: el('esc-type').value,
    situation_text: el('esc-situation').value,
    title: el('esc-title').value || null,
    listed_price: numOrNull('esc-listed'),
    proposed_value: numOrNull('esc-proposed'),
    budget_cap: numOrNull('esc-budget'),
    agent_confidence: parseFloat(el('esc-conf').value || '0.5'),
  }};
  try {{
    const {{body}} = await postJSON('/api/escalate', payload);
    if (!body.ok) {{ panel.innerHTML = statusBar(false, 'Escalate failed') + jsonBlock(body); return; }}
    const d = body.decision;
    let html = statusBar(true, body.sms_sent ? 'Routed · SMS sent' : 'Routed · no delegation (router declined)');
    html += '<p class="kv">Routed to <b>'+d.target_person+'</b> · urgency <b>'+d.urgency_tier+'</b></p>';
    html += '<p class="kv">"'+escapeHtml(d.suggested_message||'')+'"</p>';
    if (d.rationale) html += '<p class="kv" style="color:var(--faint)">'+escapeHtml(d.rationale)+'</p>';
    if (body.reply_link) html += '<a class="link" href="'+body.reply_link+'" target="_blank" rel="noopener">'+body.reply_link+'</a>';
    html += jsonBlock(d, 'Routing decision');
    panel.innerHTML = html;
  }} catch(e) {{ panel.innerHTML = statusBar(false, 'Request error') + '<pre>'+escapeHtml(String(e))+'</pre>'; }}
  finally {{ btn.disabled = false; }}
}}
function numOrNull(id){{ const v = el(id).value; return v === '' ? null : parseFloat(v); }}

// ── 2 · call ────────────────────────────────────────────────────────────────
async function placeCall(btn){{
  const panel = el('call-result'); btn.disabled = true; setRunning(panel, 'Creating delegation &amp; dialing…');
  const payload = {{
    to: el('call-to').value || null,
    person: el('call-person').value || 'the procurement lead',
    context: el('call-context').value || null,
  }};
  try {{
    const {{body}} = await postJSON('/api/call', payload);
    if (!body.ok) {{
      panel.innerHTML = statusBar(false, 'Call not placed'+(body.stage?(' · '+body.stage):'')) + jsonBlock(body);
      return;
    }}
    let html = statusBar(true, 'Call initiated to '+body.to);
    const cr = body.call_result || {{}};
    if (cr.call_control_id) html += '<p class="kv">Telnyx call_control_id <b class="mono">'+escapeHtml(cr.call_control_id)+'</b></p>';
    html += '<p class="kv">request_id <b class="mono">'+escapeHtml(body.request_id||'')+'</b> · the bridge will resolve this when the human decides.</p>';
    if (body.reply_link) html += '<a class="link" href="'+body.reply_link+'" target="_blank" rel="noopener">'+body.reply_link+'</a>';
    html += jsonBlock(body.call_result, 'Voice /call response');
    panel.innerHTML = html;
  }} catch(e) {{ panel.innerHTML = statusBar(false, 'Request error') + '<pre>'+escapeHtml(String(e))+'</pre>'; }}
  finally {{ btn.disabled = false; }}
}}

// ── 3 · raw sms ─────────────────────────────────────────────────────────────
async function sendRaw(btn){{
  const panel = el('raw-result'); btn.disabled = true; setRunning(panel, 'Sending…');
  const payload = {{ to: el('raw-to').value || null, text: el('raw-text').value }};
  try {{
    const {{body}} = await postJSON('/api/raw-sms', payload);
    if (!body.ok) {{ panel.innerHTML = statusBar(false, 'Send failed') + jsonBlock(body); return; }}
    const s = body.summary || {{}};
    let html = statusBar(true, 'Sent to '+(s.to||''));
    html += '<p class="kv">id <b class="mono">'+escapeHtml(s.id||'')+'</b> · from <b>'+escapeHtml(s.from||'')+'</b></p>';
    html += jsonBlock(body.telnyx, 'Telnyx response');
    panel.innerHTML = html;
  }} catch(e) {{ panel.innerHTML = statusBar(false, 'Request error') + '<pre>'+escapeHtml(String(e))+'</pre>'; }}
  finally {{ btn.disabled = false; }}
}}

// ── 4 · pending ─────────────────────────────────────────────────────────────
const TIER = {{async:'routine', urgent_push:'time-sensitive', voice:'urgent · call'}};
async function loadPending(btn){{
  const panel = el('pend-result'); if (btn) btn.disabled = true; setRunning(panel, 'Loading…');
  try {{
    const r = await fetch('/api/pending'); const body = await r.json();
    if (!body.ok) {{ panel.innerHTML = statusBar(false, 'Fetch failed') + jsonBlock(body); return; }}
    let html = statusBar(true, body.count + ' open delegation' + (body.count===1?'':'s'));
    if (body.count === 0) {{
      html += '<p class="kv" style="color:var(--faint)">Nothing waiting on a human right now.</p>';
    }} else {{
      html += '<div class="pend">';
      body.pending.forEach(d => {{
        html += '<div class="pend-item"><p class="pm">'+escapeHtml(d.suggested_message||'')+'</p>'+
          '<div class="pend-meta">'+
          '<span class="pill">'+escapeHtml(d.target_person||'')+'</span>'+
          '<span class="pill '+escapeHtml(d.urgency_tier||'')+'">'+(TIER[d.urgency_tier]||d.urgency_tier)+'</span>'+
          '<span>'+escapeHtml((d.request_id||'').slice(0,8))+'</span>'+
          '<a href="/api/pending" style="display:none"></a>'+
          '</div></div>';
      }});
      html += '</div>';
    }}
    html += jsonBlock(body.pending, 'Raw /pending');
    panel.innerHTML = html;
  }} catch(e) {{ panel.innerHTML = statusBar(false, 'Request error') + '<pre>'+escapeHtml(String(e))+'</pre>'; }}
  finally {{ if (btn) btn.disabled = false; }}
}}
// auto-load on first paint
loadPending(document.getElementById('pend-btn'));
</script>
</body></html>"""
    return _HEAD + body
