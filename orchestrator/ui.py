"""The mission launcher page — sivra design language (warm paper, Fraunces +
Inter). One self-contained HTML doc: a goal box + "Launch mission", then a live
status panel that polls /status and links straight into Mission Control and the
supervisor's pending queue (with per-escalation reply links).
"""
from __future__ import annotations

_MARK = (
    '<svg class="mark" width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">'
    '<circle cx="11" cy="11" r="9.2" stroke="currentColor" stroke-width="1.1" opacity=".45"/>'
    '<circle cx="11" cy="11" r="2.6" fill="currentColor"/>'
    '<circle cx="19.4" cy="11" r="1.9" fill="currentColor"/></svg>'
)

_CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
:root{--paper:#F4F2EB;--card:#FBFAF5;--ink:#1B1A15;--muted:#615D52;--faint:#A39E8E;
--line:#E5E1D5;--line2:#EFEBE0;--accent:#3A357C;--warm:#A6592B;--ok:#2E7D52;--okbg:#E8F2EC;
--serif:'Fraunces',Georgia,serif;--sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
--mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.55;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;min-height:100dvh}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
background:radial-gradient(120% 70% at 50% -10%,rgba(58,53,124,.07),transparent 62%)}
.mono{font-family:var(--mono)}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.bar{padding:18px 26px;border-bottom:1px solid var(--line);background:rgba(244,242,235,.86);
backdrop-filter:saturate(1.1) blur(10px);position:sticky;top:0;z-index:5}
.bar-row{display:flex;align-items:center;gap:14px;max-width:1080px;margin:0 auto}
.brand{display:inline-flex;align-items:center;gap:9px;color:var(--ink)}
.brand .mark{color:var(--accent)}.brand .wm{font-family:var(--serif);font-size:20px;font-weight:500}
.brand .wm small{color:var(--faint);font-weight:400}
.spacer{flex:1}
.link{font-family:var(--mono);font-size:12px;color:var(--muted)}
.wrap{max-width:1080px;margin:0 auto;padding:42px 26px 72px}
h1{font-family:var(--serif);font-weight:400;font-size:34px;line-height:1.18;letter-spacing:-.01em;margin:0 0 10px}
.sub{color:var(--muted);font-size:15px;max-width:60ch;margin:0 0 30px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:26px;
box-shadow:0 1px 1px rgba(27,26,21,.03),0 24px 56px -28px rgba(27,26,21,.16);margin-bottom:24px}
label.k{display:block;font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
color:var(--faint);margin-bottom:9px}
.goalrow{display:flex;gap:12px;flex-wrap:wrap;align-items:stretch}
.field{flex:1;min-width:260px;display:flex;align-items:center;border:1px solid var(--line);border-radius:13px;
padding:0 16px;background:#fff}
.field input{border:0;background:transparent;width:100%;padding:16px 6px;font-size:16px;font-family:inherit;
color:var(--ink);outline:none}
.nfield{display:flex;align-items:center;border:1px solid var(--line);border-radius:13px;padding:0 14px;background:#fff}
.nfield input{border:0;background:transparent;width:66px;padding:16px 4px;font-size:16px;font-family:var(--mono);
color:var(--ink);outline:none;text-align:center}
.nfield .cap{color:var(--faint);font-size:12px;font-family:var(--mono)}
.btn{border:0;border-radius:13px;padding:0 26px;font-size:15px;font-weight:600;font-family:inherit;cursor:pointer;
background:var(--ink);color:#FBFAF5;transition:.13s}.btn:hover{background:#34322a}
.btn:disabled{opacity:.5;cursor:default}
.examples{margin-top:16px;display:flex;gap:9px;flex-wrap:wrap}
.ex{font-family:var(--mono);font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:9px;
padding:7px 11px;background:#fff;cursor:pointer;transition:.12s}.ex:hover{border-color:#cfc9b9;color:var(--ink)}
.row{display:flex;gap:14px;flex-wrap:wrap;margin-top:18px}
.pill{font-family:var(--mono);font-size:11.5px;color:var(--muted);border:1px solid var(--line);border-radius:999px;
padding:6px 13px;background:var(--card)}.pill b{color:var(--ink)}
.statline{font-family:var(--mono);font-size:12px;color:var(--muted);margin:0 0 14px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--faint);margin-right:7px;vertical-align:middle}
.dot.run{background:var(--ok);animation:p 1.6s infinite}.dot.esc{background:var(--warm)}.dot.err{background:#b3402e}
@keyframes p{0%{box-shadow:0 0 0 0 rgba(46,125,82,.5)}70%{box-shadow:0 0 0 7px rgba(46,125,82,0)}100%{box-shadow:0 0 0 0 rgba(46,125,82,0)}}
.mlist{display:flex;flex-direction:column;gap:14px}
.mission{border:1px solid var(--line);border-radius:14px;padding:18px;background:#fff}
.mission h3{font-family:var(--serif);font-weight:500;font-size:18px;margin:0 0 4px}
.mission .meta{font-family:var(--mono);font-size:11.5px;color:var(--faint);margin-bottom:12px}
.badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.b{font-family:var(--mono);font-size:11px;border-radius:8px;padding:5px 9px;border:1px solid var(--line);color:var(--muted)}
.b.running{color:var(--ok);background:var(--okbg);border-color:#cfe6da}
.b.escalated{color:var(--warm);background:#FBEFE6;border-color:#ECD7C4}
.b.done{color:var(--accent);background:rgba(58,53,124,.06);border-color:#d3d0e6}
.esclist{margin-top:8px;border-top:1px solid var(--line2);padding-top:12px}
.esc{display:flex;align-items:center;gap:10px;font-size:13px;padding:6px 0}
.esc .who{font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.esc .verdict{font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:7px;border:1px solid var(--line)}
.esc .verdict.waiting{color:var(--warm);background:#FBEFE6;border-color:#ECD7C4}
.esc .verdict.approve{color:var(--ok);background:var(--okbg);border-color:#cfe6da}
.esc .verdict.decline{color:#b3402e}
.empty{color:var(--faint);font-size:14px}
.cta{display:inline-flex;align-items:center;gap:7px;font-weight:600}
"""

_JS = """
const $ = s => document.querySelector(s);
const MC = %MC%, SUP = %SUP%;

function setExamples(){
  document.querySelectorAll('.ex').forEach(e=>e.onclick=()=>{ $('#goal').value = e.textContent; $('#goal').focus(); });
}

async function launch(){
  const goal = $('#goal').value.trim();
  if(!goal){ $('#goal').focus(); return; }
  const n = parseInt($('#n').value) || 12;
  $('#go').disabled = true; $('#go').textContent = 'Launching…';
  try{
    const r = await fetch('/launch', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({goal, n})});
    const d = await r.json();
    if(!d.ok){ alert(d.error||'launch failed'); }
    else { window.__lastMission = d.mission_id; }
  }catch(e){ alert('launch error: '+e); }
  $('#go').disabled = false; $('#go').textContent = 'Launch mission';
  refresh();
}

function verdictClass(e){
  if(!e.resolved) return 'waiting';
  if(e.resolution==='approve') return 'approve';
  if(e.resolution==='decline') return 'decline';
  return 'approve';
}
function verdictLabel(e){
  if(!e.resolved) return 'awaiting human';
  return e.resolution || 'resolved';
}

function renderMission(m){
  const bs = m.by_status||{};
  const statusBadges = Object.entries(bs).map(([k,v])=>`<span class="b ${k}">${k} ${v}</span>`).join('');
  const dotClass = m.status==='running' ? (bs.escalated? 'esc':'run') : (m.status==='error'?'err':'');
  const escs = (m.escalations||[]).map(e=>`
    <div class="esc">
      <span class="who">${e.agent_id} · ${e.decision_type||'decision'}</span>
      <span class="verdict ${verdictClass(e)}">${verdictLabel(e)}</span>
      ${e.reply_url? `<a href="${e.reply_url}" target="_blank">reply ↗</a>`:''}
    </div>`).join('');
  const p = m.parsed||{};
  const parsedStr = p.recognised
    ? `category <b>${p.category}</b>${p.brand?` · brand ${p.brand}`:''}${p.budget_eur?` · ≤€${p.budget_eur}`:''}`
    : `free sample (category not recognised)`;
  return `<div class="mission">
    <h3>“${m.goal}”</h3>
    <div class="meta">${m.mission_id} · ${m.n} agents · ${parsedStr} · ${m.elapsed_s}s · ${m.pushes} pushes${m.last_push_ok===false?' ⚠ push failing':''}</div>
    <div class="badges"><span class="dot ${dotClass}"></span><span class="b">${m.status}</span>${statusBadges}</div>
    ${escs? `<div class="esclist"><div class="meta">human-in-the-loop escalations</div>${escs}</div>`:''}
  </div>`;
}

async function refresh(){
  try{
    const r = await fetch('/status',{cache:'no-store'});
    const d = await r.json();
    const ms = d.missions||[];
    $('#mlist').innerHTML = ms.length
      ? ms.slice().reverse().map(renderMission).join('')
      : '<div class="empty">No missions yet — type a goal above and hit Launch mission.</div>';
    const anyEsc = ms.some(m=>(m.by_status||{}).escalated);
    $('#supnote').style.display = anyEsc ? 'inline' : 'none';
  }catch(e){}
}

document.addEventListener('DOMContentLoaded',()=>{
  setExamples();
  $('#go').onclick = launch;
  $('#goal').addEventListener('keydown',e=>{ if(e.key==='Enter') launch(); });
  refresh(); setInterval(refresh, 1500);
});
"""


def render_launcher(*, mission_control_url: str, supervisor_url: str,
                    endpoint: str, default_n: int, categories: list[str]) -> str:
    import json as _json
    js = (_JS
          .replace("%MC%", _json.dumps(mission_control_url))
          .replace("%SUP%", _json.dumps(supervisor_url)))
    cats = " · ".join(categories)
    examples = [
        "a used road bike, 56cm, under €400",
        "a OnePlus phone under €300",
        "a refurbished ThinkPad laptop, max €600",
        "a mirrorless camera under €500",
    ]
    ex_html = "".join(f'<span class="ex">{e}</span>' for e in examples)
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sivra · mission orchestrator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body>
<header class="bar"><div class="bar-row">
  <a class="brand" href="/">{_MARK}<span class="wm">sivra <small>· mission orchestrator</small></span></a>
  <span class="spacer"></span>
  <a class="link" href="{mission_control_url}" target="_blank">mission control ↗</a>
  <a class="link" href="{supervisor_url}/pending" target="_blank">supervisor pending ↗</a>
</div></header>

<main class="wrap">
  <h1>Type a goal. Spawn a fleet of buyer agents.</h1>
  <p class="sub">One goal becomes N computer-use agents shopping the live marketplace in parallel.
  Watch them work on <a href="{mission_control_url}" target="_blank">Mission Control</a>; when an agent
  hits a decision a human should own, it escalates to the
  <a href="{supervisor_url}/pending" target="_blank">supervisor</a> (phone / SMS / web) and waits for the verdict.</p>

  <div class="card">
    <label class="k" for="goal">Mission goal</label>
    <div class="goalrow">
      <div class="field"><input id="goal" placeholder="a used road bike, 56cm, under €400" autocomplete="off"></div>
      <div class="nfield"><input id="n" type="number" min="1" max="100" value="{default_n}"><span class="cap">agents</span></div>
      <button class="btn" id="go">Launch mission</button>
    </div>
    <div class="examples">{ex_html}</div>
    <div class="row">
      <span class="pill">policy <b>Modal · Gemma-4</b></span>
      <span class="pill">categories <b>{cats}</b></span>
      <span class="pill">sites <b>site-a/b/c</b></span>
    </div>
  </div>

  <div class="card">
    <p class="statline"><span class="dot"></span>Live missions · pushing snapshots to Mission Control every ~1s
      <span id="supnote" style="display:none">· <a href="{supervisor_url}/pending" target="_blank">a human is needed ↗</a></span></p>
    <div class="mlist" id="mlist"><div class="empty">No missions yet — type a goal above and hit Launch mission.</div></div>
  </div>
</main>
<script>{js}</script>
</body></html>"""
