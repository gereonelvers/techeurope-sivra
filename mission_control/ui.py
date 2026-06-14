"""The single Mission Control page — sivra design language, control-room layout.

Returns one self-contained HTML document. All motion is client-side: a poll loop
hits /api/fleet, diffs the snapshot into a fixed grid of tiles, and flashes green
on a freshly-completed run. Warm-paper sivra palette, Fraunces + Inter, mono
micro-labels, hairline borders — but composed as a dense ops console.
"""
from __future__ import annotations

import json
from typing import Any

_MARK = (
    '<svg class="mark" width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">'
    '<circle cx="11" cy="11" r="9.2" stroke="currentColor" stroke-width="1.1" opacity=".45"/>'
    '<circle cx="11" cy="11" r="2.6" fill="currentColor"/>'
    '<circle cx="19.4" cy="11" r="1.9" fill="currentColor"/></svg>'
)

_CSS = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
:root{
  --paper:#F4F2EB;--card:#FBFAF5;--ink:#1B1A15;--muted:#615D52;--faint:#A39E8E;
  --line:#E5E1D5;--line2:#EFEBE0;--accent:#3A357C;--warm:#A6592B;--ok:#2E7D52;--okbg:#E8F2EC;
  --serif:'Fraunces',Georgia,serif;
  --sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,monospace}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;min-height:100dvh}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
  background:radial-gradient(120% 70% at 50% -10%,rgba(58,53,124,.07),transparent 62%)}
.mono{font-family:var(--mono)}
a{color:inherit}

/* ── top bar ───────────────────────────────────────────────────────────── */
.bar{position:sticky;top:0;z-index:20;background:rgba(244,242,235,.86);
  backdrop-filter:saturate(1.1) blur(10px);border-bottom:1px solid var(--line);
  padding:14px 26px 13px}
.bar-row{display:flex;align-items:center;gap:22px;max-width:1680px;margin:0 auto;flex-wrap:wrap}
.brand{display:inline-flex;align-items:center;gap:9px;color:var(--ink);text-decoration:none;flex:0 0 auto}
.brand .mark{color:var(--accent)}
.brand .wm{font-family:var(--serif);font-size:20px;font-weight:500;letter-spacing:-.01em}
.brand .wm small{color:var(--faint);font-weight:400}
.live{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:10.5px;
  letter-spacing:.16em;text-transform:uppercase;color:var(--muted);
  border:1px solid var(--line);border-radius:999px;padding:5px 11px;background:var(--card)}
.live .pulse{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(46,125,82,.5);
  animation:pulse 1.8s infinite}
.live.replay .pulse{background:var(--warm);animation:pulse 2.4s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(46,125,82,.45)}70%{box-shadow:0 0 0 7px rgba(46,125,82,0)}100%{box-shadow:0 0 0 0 rgba(46,125,82,0)}}
.spacer{flex:1 1 auto}

.stats{display:flex;gap:0;align-items:stretch;flex-wrap:wrap}
.stat{padding:2px 18px;border-left:1px solid var(--line);min-width:84px}
.stat:first-child{border-left:0;padding-left:0}
.stat .k{font-family:var(--mono);font-size:9.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--faint);white-space:nowrap}
.stat .v{font-family:var(--serif);font-size:23px;font-weight:500;letter-spacing:-.01em;line-height:1.15;margin-top:2px}
.stat .v small{font-family:var(--sans);font-size:12px;color:var(--muted);font-weight:500}
.stat .v.acc{color:var(--accent)}.stat .v.ok{color:var(--ok)}
.stat .sub{font-size:10.5px;color:var(--faint);margin-top:1px}

/* model + cost chips */
.chips{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;color:var(--muted);
  border:1px solid var(--line);border-radius:8px;padding:6px 10px;background:var(--card);white-space:nowrap}
.chip b{color:var(--ink);font-weight:600}
.chip.cost b{color:var(--ok)}
.chip .x{color:var(--warm)}

/* ── grid ──────────────────────────────────────────────────────────────── */
.stage{max-width:1680px;margin:0 auto;padding:18px 22px 40px}
.grid{display:grid;gap:11px;
  grid-template-columns:repeat(auto-fill,minmax(208px,1fr))}
.tile{position:relative;background:var(--card);border:1px solid var(--line);border-radius:13px;
  overflow:hidden;box-shadow:0 1px 1px rgba(27,26,21,.03),0 14px 30px -22px rgba(27,26,21,.18);
  transition:border-color .25s,box-shadow .25s,transform .25s}
.tile:hover{transform:translateY(-2px);box-shadow:0 1px 1px rgba(27,26,21,.04),0 22px 40px -22px rgba(27,26,21,.28);
  border-color:#D6D1C2}
.shot{position:relative;aspect-ratio:1280/800;background:#ece9df;overflow:hidden}
.shot img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:top center;
  display:block;transition:opacity .18s}
.shot::after{content:"";position:absolute;inset:0;
  box-shadow:inset 0 0 0 1px rgba(27,26,21,.04),inset 0 -22px 26px -22px rgba(27,26,21,.28)}
/* the cursor dot of the next click */
.cursor{position:absolute;width:14px;height:14px;border-radius:50%;border:1.5px solid var(--accent);
  background:rgba(58,53,124,.18);transform:translate(-50%,-50%);transition:left .25s,top .25s;
  pointer-events:none;display:none;box-shadow:0 0 0 4px rgba(58,53,124,.08)}

.head{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:6px;
  padding:7px 9px;background:linear-gradient(180deg,rgba(251,250,245,.95),rgba(251,250,245,0));z-index:2}
.aid{font-family:var(--mono);font-size:9.5px;letter-spacing:.04em;color:var(--muted)}
.site{font-family:var(--mono);font-size:9.5px;color:var(--faint);margin-left:auto}

.badge{position:absolute;left:9px;bottom:9px;z-index:2;display:inline-flex;align-items:center;gap:5px;
  font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
  padding:4px 8px;border-radius:999px;background:rgba(251,250,245,.92);border:1px solid var(--line);color:var(--muted)}
.badge .d{width:6px;height:6px;border-radius:50%;background:var(--faint)}
.badge[data-s=searching] .d{background:#6b6fb0}.badge[data-s=searching]{color:var(--accent)}
.badge[data-s=filtering] .d{background:#7d79b8}
.badge[data-s=viewing] .d{background:#9a7bbf}
.badge[data-s=cart] .d{background:var(--warm)}.badge[data-s=cart]{color:var(--warm)}
.badge[data-s=checkout] .d{background:var(--warm)}.badge[data-s=checkout]{color:var(--warm)}
.badge[data-s=done] .d{background:var(--ok)}.badge[data-s=done]{color:var(--ok);background:var(--okbg);border-color:#cfe6da}
/* escalated = waiting on a human decision (routed to the supervisor) */
.badge[data-s=escalated] .d{background:var(--warm);animation:pulse-d 1.4s infinite}
.badge[data-s=escalated]{color:var(--warm);background:#FBEFE6;border-color:#ECD7C4}
@keyframes pulse-d{0%,100%{opacity:1}50%{opacity:.35}}
/* a tile waiting on a human gets a warm ring + a small banner so it pops in the grid */
.tile.escalated{border-color:var(--warm);box-shadow:0 0 0 1px var(--warm),0 14px 30px -22px rgba(166,89,43,.4)}
.tile.escalated .shot::before{content:"awaiting human";position:absolute;z-index:3;left:0;right:0;top:0;
  font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:#fff;
  background:linear-gradient(180deg,rgba(166,89,43,.96),rgba(166,89,43,.78));padding:5px 9px;text-align:center}

.step{position:absolute;right:9px;bottom:9px;z-index:2;font-family:var(--mono);font-size:9.5px;
  color:var(--muted);background:rgba(251,250,245,.9);border:1px solid var(--line);border-radius:7px;padding:3px 7px}

.body{padding:9px 11px 11px}
.goal{font-family:var(--serif);font-size:13.5px;font-weight:500;letter-spacing:-.005em;color:var(--ink);
  line-height:1.28;min-height:2.5em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.act{font-family:var(--mono);font-size:11px;color:var(--accent);margin-top:6px;display:flex;align-items:center;gap:6px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.act .caret{color:var(--faint)}

/* success flash */
.tile.flash{animation:flash 1.1s ease-out}
@keyframes flash{0%{box-shadow:0 0 0 2px var(--ok),0 0 26px 2px rgba(46,125,82,.45)}
  100%{box-shadow:0 1px 1px rgba(27,26,21,.03),0 14px 30px -22px rgba(27,26,21,.18)}}
.tile.flash .shot::before{content:"";position:absolute;inset:0;z-index:3;background:rgba(46,125,82,.16);animation:fade 1.1s ease-out forwards}
@keyframes fade{to{opacity:0}}
.done-mark{position:absolute;inset:0;z-index:4;display:none;align-items:center;justify-content:center;pointer-events:none}
.tile.flash .done-mark{display:flex}
.done-mark .ring{width:46px;height:46px;border-radius:50%;background:var(--ok);color:#fff;display:flex;
  align-items:center;justify-content:center;font-size:22px;box-shadow:0 8px 22px -6px rgba(46,125,82,.6);animation:pop .5s ease-out}
@keyframes pop{0%{transform:scale(.4);opacity:0}60%{transform:scale(1.08)}100%{transform:scale(1);opacity:1}}

.foot{max-width:1680px;margin:6px auto 0;padding:18px 22px 0;border-top:1px solid var(--line2);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--faint)}
.foot .mono{color:var(--muted)}
.skel{background:linear-gradient(100deg,#ece9df 30%,#f4f1e8 50%,#ece9df 70%);background-size:200% 100%;animation:sh 1.3s infinite}
@keyframes sh{to{background-position:-200% 0}}

@media(max-width:760px){.stat{padding:2px 11px;min-width:66px}.stat .v{font-size:18px}
  .grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}.bar{padding:12px 14px}}
"""

_JS = """
const FLEET_SIZE = %FLEET_SIZE%;
const grid = document.getElementById('grid');
const tiles = new Map();          // agent_id -> {el, refs, status, step}
let firstPaint = true;

// Render an action to a human-readable line. Accepts either the dashboard's
// string form ('click (412, 233)') OR the live fleet's raw dict
// ({action:'click',x:412,y:233}) so the same grid drives replay AND live.
function actionStr(action){
  if(action == null) return '';
  if(typeof action === 'string') return action;
  const a = action.action;
  if(a === 'click') return `click (${action.x}, ${action.y})`;
  if(a === 'type') return `type "${action.text ?? ''}"`;
  if(a === 'scroll') return `scroll ${action.dy ?? ''}`;
  if(a === 'navigate_back') return 'navigate back';
  if(a === 'done') return 'done ✓';
  return a || JSON.stringify(action);
}

// click-target heuristic: parse a click action to place the cursor dot (coords are
// in the original 1280x800 frame; the tile shows it object-fit:cover from the top).
function parseClick(action){
  if(action && typeof action === 'object' && action.action === 'click'){
    return {x:+action.x/1280*100, y:+action.y/800*100};
  }
  const s = typeof action === 'string' ? action : '';
  const m = s.match(/click \\((\\d+),\\s*(\\d+)\\)/);
  if(!m) return null;
  return {x:+m[1]/1280*100, y:+m[2]/800*100};
}

function makeTile(a){
  const el = document.createElement('div');
  el.className='tile';
  el.innerHTML = `
    <div class="shot">
      <div class="head"><span class="aid"></span><span class="site"></span></div>
      <img alt="" loading="lazy">
      <span class="cursor"></span>
      <span class="badge"><span class="d"></span><span class="t"></span></span>
      <span class="step"></span>
      <div class="done-mark"><div class="ring">✓</div></div>
    </div>
    <div class="body">
      <div class="goal"></div>
      <div class="act"><span class="caret">›</span><span class="t"></span></div>
    </div>`;
  const refs = {
    img: el.querySelector('img'), aid: el.querySelector('.aid'),
    site: el.querySelector('.site'), badge: el.querySelector('.badge'),
    badgeT: el.querySelector('.badge .t'), step: el.querySelector('.step'),
    goal: el.querySelector('.goal'), act: el.querySelector('.act .t'),
    cursor: el.querySelector('.cursor')
  };
  const rec = {el, refs, status:null, step:null, shot:null};
  tiles.set(a.agent_id, rec);
  return rec;
}

function paint(rec, a){
  const r = rec.refs;
  if(rec.aid !== a.agent_id){ r.aid.textContent = a.agent_id; rec.aid=a.agent_id; }
  if(rec.site !== a.site){ r.site.textContent = a.site; rec.site=a.site; }
  if(rec.goal !== a.goal){ r.goal.textContent = a.goal; rec.goal=a.goal; }
  // screenshot
  if(rec.shot !== a.screenshot_url){
    r.img.classList.add('sw');
    r.img.src = a.screenshot_url; rec.shot = a.screenshot_url;
  }
  // action + cursor
  r.act.textContent = actionStr(a.action);
  const c = parseClick(a.action);
  if(c && a.status!=='done'){ r.cursor.style.display='block'; r.cursor.style.left=c.x+'%'; r.cursor.style.top=c.y+'%'; }
  else { r.cursor.style.display='none'; }
  // badge + step
  if(rec.status !== a.status){
    rec.el.querySelector('.badge').dataset.s = a.status; r.badgeT.textContent = a.status;
    rec.el.classList.toggle('escalated', a.status==='escalated');
  }
  r.step.textContent = `${a.step}/${a.n_steps}`;
  // success flash: a fresh 'done' that we didn't already show
  const wasDone = rec.status==='done';
  if(a.status==='done' && !wasDone && !firstPaint){
    rec.el.classList.remove('flash'); void rec.el.offsetWidth; rec.el.classList.add('flash');
  }
  rec.status = a.status; rec.step = a.step;
}

function setStats(s){
  const set=(id,v)=>{const e=document.getElementById(id); if(e) e.textContent=v;};
  set('s-active', s.active);
  set('s-success', (s.success_rate*100).toFixed(1)+'%');
  set('s-success-sub', `${s.corpus_success}/${s.corpus_trajectories} runs kept`);
  set('s-avg', s.avg_steps);
  set('s-tpm', s.tasks_per_min);
  set('c-model', s.model);
  set('c-ours', '$'+s.cost_ours.toFixed(3));
  set('c-frontier', '$'+s.cost_frontier.toLocaleString(undefined,{maximumFractionDigits:0}));
  set('c-ratio', s.cost_ratio.toLocaleString()+'×');
  const liveEl=document.getElementById('liveTag');
  if(liveEl){ const live = (window.__src==='live'); liveEl.classList.toggle('replay', !live);
    liveEl.querySelector('.lt').textContent = live ? 'live fleet' : 'recorded replay'; }
}

async function tick(){
  try{
    const res = await fetch(`/api/fleet?n=${FLEET_SIZE}`, {cache:'no-store'});
    const data = await res.json();
    window.__src = data.source;
    // ensure tiles exist in order
    if(firstPaint){
      grid.innerHTML='';
      data.agents.forEach(a=>{ const rec=makeTile(a); grid.appendChild(rec.el); paint(rec,a); });
    } else {
      data.agents.forEach(a=>{ let rec=tiles.get(a.agent_id); if(!rec){ rec=makeTile(a); grid.appendChild(rec.el);} paint(rec,a); });
    }
    setStats(data.stats);
    firstPaint=false;
  }catch(e){ /* keep last frame on a hiccup */ }
}

tick();
setInterval(tick, %POLL_MS%);
document.addEventListener('visibilitychange',()=>{ if(!document.hidden) tick(); });
"""


def render_page(meta: dict[str, Any]) -> str:
    fleet_size = 100
    poll_ms = 1600
    js = _JS.replace("%FLEET_SIZE%", str(fleet_size)).replace("%POLL_MS%", str(poll_ms))
    sr = round(meta["success_rate"] * 100, 1)
    sub_runs = f"{meta['corpus_success']}/{meta['corpus_trajectories']} runs kept"
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sivra · mission control</title>
<meta name="description" content="A live grid of ~100 buyer agents operating the marketplace in parallel.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body>
<header class="bar"><div class="bar-row">
  <a class="brand" href="/">{_MARK}<span class="wm">sivra <small>· mission control</small></span></a>
  <span class="live" id="liveTag"><span class="pulse"></span><span class="lt mono">recorded replay</span></span>
  <span class="spacer"></span>
  <div class="stats">
    <div class="stat"><div class="k">Agents live</div><div class="v acc" id="s-active">—</div><div class="sub">computer-use, parallel</div></div>
    <div class="stat"><div class="k">Success rate</div><div class="v ok" id="s-success">{sr}%</div><div class="sub" id="s-success-sub">{sub_runs}</div></div>
    <div class="stat"><div class="k">Avg steps</div><div class="v" id="s-avg">{meta['avg_steps']}</div><div class="sub">per task, end-to-end</div></div>
    <div class="stat"><div class="k">Tasks / min</div><div class="v" id="s-tpm">—</div><div class="sub">across the fleet</div></div>
  </div>
  <span class="spacer"></span>
  <div class="chips">
    <span class="chip">model <b id="c-model">{meta['model']}</b></span>
    <span class="chip cost">spend <b id="c-ours">—</b> <span class="x">vs</span> frontier <b id="c-frontier" style="color:var(--warm)">—</b></span>
    <span class="chip">cost edge <b id="c-ratio" style="color:var(--ok)">—</b></span>
  </div>
</div></header>

<main class="stage">
  <div class="grid" id="grid">
    {''.join(f'<div class="tile"><div class="shot skel"></div><div class="body"><div class="goal">&nbsp;</div><div class="act">&nbsp;</div></div></div>' for _ in range(60))}
  </div>
</main>

<div class="foot">
  <span>A live grid of <b class="mono">~100</b> buyer agents shopping the marketplace in parallel — genuine recorded computer-use footage, replayed.</span>
  <span class="mono">{meta['bundled_trajectories']} trajectories · {len(meta['categories'])} categories · {len(meta['sites'])} sites · /api/fleet</span>
</div>

<script>{js}</script>
</body></html>"""
