#!/usr/bin/env python3
"""
Flask dashboard for Spurs squad book value.
Reads players.csv live via book_value.py on every request (edit CSV -> refresh).

Run:  py -3 app.py    then open http://localhost:5200
"""
import os
from flask import Flask, render_template_string, request, jsonify
import book_value as bv

app = Flask(__name__)

# Public deployment (e.g. Fly.io) sets PUBLIC_MODE=1: the page renders in shared
# mode (client-side what-ifs only) and the sale-price write endpoint is disabled,
# so no visitor can alter the data. Locally it's unset → full editing.
PUBLIC = os.environ.get("PUBLIC_MODE") == "1"

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spurs Squad Book Value — amortization & PSR tracker</title>
<meta name="description" content="Net book value, amortization and book profit on sale for every Tottenham Hotspur player, with a Sell XI simulator and PSR headroom tracker.">
<meta property="og:type" content="website">
<meta property="og:title" content="Tottenham Hotspur — Squad Book Value">
<meta property="og:description" content="Transfer-fee amortization & book profit for every Spurs player. Interactive Sell XI simulator + PSR headroom tracker.">
<meta property="og:url" content="https://thisismyback.github.io/spurs-book-value/">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Tottenham Hotspur — Squad Book Value">
<meta name="twitter:description" content="Transfer-fee amortization & book profit for every Spurs player. Interactive Sell XI simulator + PSR headroom tracker.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='48' fill='%23132257'/><text x='50' y='70' font-size='58' text-anchor='middle' fill='white'>%C2%A3</text></svg>">
<style>
  :root{ --navy:#132257; --green:#16a34a; --red:#dc2626; --bg:#0f1424; --card:#1b2440; --line:#2a355c; }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:#e8ecf5;padding-bottom:66px}
  header{background:var(--navy);padding:20px 28px;border-bottom:3px solid #fff}
  header h1{margin:0;font-size:20px;letter-spacing:.3px}
  header .sub{opacity:.7;font-size:12px;margin-top:4px}
  .wrap{padding:22px 28px;max-width:1180px;margin:0 auto}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:14px;margin-bottom:22px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.6px;opacity:.65}
  .card .val{font-size:26px;font-weight:700;margin-top:6px}
  .card .note{font-size:11px;opacity:.6;margin-top:4px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{padding:9px 12px;text-align:right;font-size:13px;border-bottom:1px solid var(--line)}
  th{background:#202a4d;cursor:pointer;user-select:none;font-size:11px;text-transform:uppercase;letter-spacing:.5px;position:sticky;top:0}
  th:hover{background:#27325c}
  td.l,th.l{text-align:left}
  tr:hover td{background:#222d52}
  .pos{font-size:10px;background:#2a355c;border-radius:4px;padding:2px 6px;opacity:.85}
  .pos{font-size:10px;background:#2a355c;border-radius:4px;padding:2px 6px}
  .pl-pos{color:var(--green);font-weight:700}
  .pl-neg{color:var(--red);font-weight:700}
  .badge{font-size:9px;padding:1px 5px;border-radius:4px;margin-left:5px;vertical-align:middle}
  .b-loan{background:#475569}
  .b-acad{background:#7c3aed}
  .b-ext{background:#0891b2}
  .b-low{background:#b45309}
  .b-out{background:#0d9488}
  .b-sold{background:#15803d}
  .saleinp{width:62px;background:#0f1424;border:1px solid var(--line);color:#e8ecf5;border-radius:5px;
    padding:4px 6px;font-size:12px;text-align:right}
  .saleinp:focus{outline:none;border-color:#15803d;background:#10241a}
  .saleinp.has{border-color:#15803d;color:#4ade80}
  .card.accent{border-color:#15803d}
  .psr{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin-bottom:22px;
    display:flex;align-items:center;gap:24px;flex-wrap:wrap}
  .psr .hd .t{font-size:11px;text-transform:uppercase;letter-spacing:.6px;opacity:.65}
  .psr .hd .s{font-size:11px;opacity:.5;margin-top:3px}
  .psr .grp{display:flex;flex-direction:column;gap:4px}
  .psr .grp label{font-size:10px;text-transform:uppercase;letter-spacing:.5px;opacity:.6}
  .psr input{width:92px;background:#0f1424;border:1px solid var(--line);color:#e8ecf5;border-radius:6px;padding:7px 9px;font-size:14px;text-align:right}
  .psr input:focus{outline:none;border-color:#15803d}
  .psr .res{margin-left:auto;text-align:right}
  .psr .res .lbl{font-size:10px;text-transform:uppercase;letter-spacing:.4px;opacity:.6}
  .psr .res .st{font-size:11px;opacity:.75;margin-top:2px}
  .psr .barwrap{flex-basis:100%;height:8px;background:#2a355c;border-radius:4px;overflow:hidden;margin-top:6px}
  .psr .barwrap>i{display:block;height:100%;background:var(--green);transition:width .2s}
  .psr .claw{flex-basis:100%;font-size:11px;opacity:.6}
  .toolbar{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
  .toolbar button{background:#33406b;color:#fff;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:12px}
  .toolbar button:hover{background:#3f4f82}
  .toolbar .share{background:#15803d}
  .toolbar .share:hover{background:#1a9a4a}
  .toolbar .reset{background:#7c2d2d}
  .toolbar .reset:hover{background:#9a3a3a}
  .toolbar .hint{font-size:11px;opacity:.55}
  #toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);background:#15803d;color:#fff;
    padding:10px 16px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:100}
  #toast.show{opacity:1}
  input[type=checkbox]{width:16px;height:16px;cursor:pointer}
  tr.selrow td{background:#163a7a !important}
  #salebar{position:fixed;left:0;right:0;bottom:0;background:#0b1020;border-top:2px solid #fff;
    display:flex;align-items:center;gap:18px;padding:11px 28px;z-index:50;box-shadow:0 -4px 16px rgba(0,0,0,.5)}
  #salebar .ttl{font-size:12px;text-transform:uppercase;letter-spacing:.5px;opacity:.7}
  #salebar .cnt{font-size:20px;font-weight:700}
  #salebar .warn{color:#f59e0b;font-size:12px;margin-left:6px}
  #salebar .stats{display:flex;gap:26px;margin-left:auto;font-size:13px;align-items:center}
  #salebar .stats .lab{opacity:.6;font-size:11px;display:block;text-transform:uppercase;letter-spacing:.4px}
  #salebar .stats b{font-size:18px}
  #salebar button{background:#33406b;color:#fff;border:0;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:12px}
  #salebar button:hover{background:#3f4f82}
  .bar{height:6px;background:#2a355c;border-radius:3px;overflow:hidden;width:80px;display:inline-block;vertical-align:middle}
  .bar>i{display:block;height:100%;background:#f59e0b}
  .muted{opacity:.4}
  footer{padding:14px 28px;opacity:.5;font-size:11px}
</style>
</head>
<body>
<header>
  <h1>Tottenham Hotspur — Squad Book Value</h1>
  <div class="sub">As of {{ today }} · figures in £m · market values = Transfermarkt €m × {{ rate }} ·
    book profit = market value − net book value · loans excluded from totals</div>
</header>
<div class="wrap">
  {% if static %}<div style="background:#1b2440;border:1px solid var(--line);border-radius:8px;
    padding:9px 13px;font-size:12px;opacity:.85;margin-bottom:18px">
    📎 Snapshot generated {{ today }}. Type into the <b>Sale Price</b> column to run your own
    what-ifs, tick the <b>Sell XI</b> boxes, and adjust the <b>PSR panel</b> — all changes stay
    in your browser only, nothing is saved or shared.</div>{% endif %}
  <div class="cards">
    <div class="card"><div class="lbl">Acquisition cost</div><div class="val">£{{ t.fee }}m</div>
      <div class="note">already amortized £{{ t.amortized }}m</div></div>
    <div class="card"><div class="lbl">Remaining book value</div><div class="val">£{{ t.nbv }}m</div>
      <div class="note">un-amortized fees on the books</div></div>
    <div class="card"><div class="lbl">Squad market value</div><div class="val">£{{ t.mv }}m</div>
      <div class="note">Transfermarkt, owned + academy</div></div>
    <div class="card"><div class="lbl">Total book profit</div>
      <div class="val {{ 'pl-pos' if t.bp>=0 else 'pl-neg' }}" id="card-bp">£{{ t.bp }}m</div>
      <div class="note">realized + unrealized</div></div>
    <div class="card accent"><div class="lbl">Realized (agreed sales)</div>
      <div class="val {{ 'pl-pos' if t.realized>=0 else 'pl-neg' }}" id="card-real">£{{ t.realized }}m</div>
      <div class="note">locked in via SOLD prices</div></div>
    <div class="card"><div class="lbl">Unrealized (at market)</div>
      <div class="val {{ 'pl-pos' if t.unrealized>=0 else 'pl-neg' }}" id="card-unreal">£{{ t.unrealized }}m</div>
      <div class="note">still hypothetical, Transfermarkt</div></div>
  </div>

  <div class="psr">
    <div class="hd"><div class="t">PSR / FFP headroom</div>
      <div class="s">3-year rolling allowable-loss model · simplified</div></div>
    <div class="grp"><label>Allowable 3-yr loss (£m)</label>
      <input id="psr-limit" type="number" step="5" value="105" oninput="updatePSR()"></div>
    <div class="grp"><label>Assumed 3-yr loss pre-sales (£m)</label>
      <input id="psr-loss" type="number" step="5" value="0" oninput="updatePSR()"></div>
    <div class="grp"><label>Realized sale profit</label>
      <div class="val pl-pos" id="psr-realized" style="font-size:20px">£0.0m</div></div>
    <div class="res"><div class="lbl">Net PSR headroom</div>
      <div class="val" id="psr-headroom" style="font-size:26px">£0.0m</div>
      <div class="st" id="psr-status">—</div></div>
    <div class="barwrap"><i id="psr-bar" style="width:0%"></i></div>
    <div class="claw" id="psr-claw">Enter your estimated 3-yr operating loss to see net headroom.
      Realized sale profit offsets losses £-for-£.</div>
  </div>

  <div class="toolbar">
    {% if static %}<button class="share" onclick="shareScenario()">🔗 Share my scenario</button>{% endif %}
    <button onclick="clearSales()">Clear sale prices</button>
    <button class="reset" onclick="resetAll()">Reset everything</button>
    <span class="hint">{% if static %}Type sale prices &amp; tick a Sell XI, then share a link to your what-if — nothing is saved on the server.{% else %}Reset every agreed sale price back to market value.{% endif %}</span>
  </div>

  <table id="t">
    <thead><tr>
      <th title="Tick to add to the sale simulator">Sell</th>
      <th class="l" onclick="sortBy(1,true)">Player</th>
      <th class="l" onclick="sortBy(2,true)">Pos</th>
      <th onclick="sortBy(3,false)">Fee</th>
      <th onclick="sortBy(4,false)">% Amort</th>
      <th onclick="sortBy(5,false)">Net Book Value</th>
      <th onclick="sortBy(6,false)">Market Value</th>
      <th onclick="sortBy(7,false)" title="Agreed/actual sale price — overrides market value in Book P/L">Sale Price</th>
      <th onclick="sortBy(8,false)">Book P/L</th>
    </tr></thead>
    <tbody>
    {% for r in rows %}
      <tr>
        {% if r.status=='loan' %}
          <td title="Loaned in — not ours to sell"></td>
        {% else %}
          <td><input type="checkbox" class="sel" onchange="recalc(this)"
                data-bp="{{ r.book_profit_gbp_m }}"
                data-mv="{{ r.sale_price_gbp_m if r.sold else r.market_value_gbp_m }}"
                data-nbv="{{ r.nbv_gbp_m }}"></td>
        {% endif %}
        <td class="l">{{ r.player }}
          {% if r.sold %}<span class="badge b-sold" title="Agreed/actual sale price entered — used for Book P/L">SOLD £{{ r.sale_price_gbp_m }}m</span>{% endif %}
          {% if r.on_loan_at %}<span class="badge b-out" title="Spurs player out on loan at {{ r.on_loan_at }}">LOAN&rarr; {{ r.on_loan_at }}</span>{% endif %}
          {% if r.extended %}<span class="badge b-ext" title="Contract extension modelled — schedule reset">EXT</span>{% endif %}
          {% if r.status=='academy' %}<span class="badge b-acad" title="Academy product — zero acquisition cost">ACAD</span>{% endif %}
          {% if r.status=='loan' %}<span class="badge b-loan" title="Loaned in — no asset capitalized">LOAN-IN</span>{% endif %}
          {% if r.confidence=='low' %}<span class="badge b-low" title="Low-confidence input — verify">?</span>{% endif %}
        </td>
        <td class="l"><span class="pos">{{ r.position }}</span></td>
        {% if r.status=='loan' %}
          <td class="muted" data-v="-1">loan</td>
          <td class="muted" data-v="-1">—</td>
          <td class="muted" data-v="-1">—</td>
          <td data-v="{{ r.market_value_gbp_m }}">£{{ r.market_value_gbp_m }}m</td>
          <td class="muted" data-v="-1">—</td>
          <td class="muted" data-v="-9999">—</td>
        {% else %}
          <td data-v="{{ r.fee_gbp_m }}">£{{ r.fee_gbp_m }}m</td>
          <td data-v="{{ r.pct_amortized }}">
            <span class="bar"><i style="width:{{ r.pct_amortized }}%"></i></span>
            <span style="font-size:11px;opacity:.7"> {{ r.pct_amortized|int }}%</span>
          </td>
          <td data-v="{{ r.nbv_gbp_m }}">£{{ r.nbv_gbp_m }}m</td>
          <td data-v="{{ r.market_value_gbp_m }}">£{{ r.market_value_gbp_m }}m</td>
          <td data-v="{{ r.sale_price_gbp_m if r.sold else -1 }}">
            <input class="saleinp{{ ' has' if r.sold else '' }}" type="number" step="0.5" min="0"
              value="{{ r.sale_price_gbp_m if r.sold else '' }}" placeholder="—" data-player="{{ r.player }}"
              data-nbv="{{ r.nbv_gbp_m }}" data-market="{{ r.market_value_gbp_m }}" onchange="saveSale(this)"
              title="{{ 'Try a what-if sale price (£m) — local only, not saved' if static else 'Type an agreed fee (£m) — saves to players.csv' }}"></td>
          <td data-v="{{ r.book_profit_gbp_m }}" class="{{ 'pl-pos' if r.book_profit_gbp_m>=0 else 'pl-neg' }}">
            {{ '+' if r.book_profit_gbp_m>=0 else '' }}£{{ r.book_profit_gbp_m }}m</td>
        {% endif %}
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>

<div id="salebar">
  <div><span class="ttl">Sell XI simulator</span><br>
    <span class="cnt" id="sb-count">0</span> selected<span class="warn" id="sb-warn"></span></div>
  <div class="stats">
    <span><span class="lab">Cash in (market value)</span><b id="sb-mv">£0.0m</b></span>
    <span><span class="lab">Book value wiped off</span><b id="sb-nbv">£0.0m</b></span>
    <span><span class="lab">PSR / FFP book profit</span><b id="sb-bp" class="pl-pos">£0.0m</b></span>
    <button onclick="clearSel()">Clear</button>
  </div>
</div>

<div id="toast"></div>

<footer>Tick players to model a sale · SOLD £x = agreed price (overrides market value in Book P/L) ·
  LOAN&rarr; = ours, out on loan · EXT = extension reset modelled · ACAD = academy (NBV £0) ·
  LOAN-IN = loaned in (not sellable) · ? = low-confidence fee.
  Edit players.csv and refresh. Source of truth: book_value.py engine.</footer>

<script>
let lastCol=-1, asc=false;
function sortBy(col, isText){
  const tb=document.querySelector('#t tbody');
  const rows=[...tb.rows];
  asc = (col===lastCol) ? !asc : false; lastCol=col;
  rows.sort((a,b)=>{
    let x,y;
    if(isText){ x=a.cells[col].innerText.trim().toLowerCase(); y=b.cells[col].innerText.trim().toLowerCase();
      return asc ? x.localeCompare(y) : y.localeCompare(x); }
    x=parseFloat(a.cells[col].dataset.v); y=parseFloat(b.cells[col].dataset.v);
    return asc ? x-y : y-x;
  });
  rows.forEach(r=>tb.appendChild(r));
}
const $=id=>document.getElementById(id);
function recalc(cb){
  if(cb){ cb.closest('tr').classList.toggle('selrow', cb.checked); }
  let n=0,mv=0,nbv=0,bp=0;
  document.querySelectorAll('.sel:checked').forEach(c=>{
    n++; mv+=+c.dataset.mv; nbv+=+c.dataset.nbv; bp+=+c.dataset.bp;
  });
  $('sb-count').textContent=n;
  $('sb-mv').textContent='£'+mv.toFixed(1)+'m';
  $('sb-nbv').textContent='£'+nbv.toFixed(1)+'m';
  const b=$('sb-bp');
  b.textContent=(bp>=0?'+':'')+'£'+bp.toFixed(1)+'m';
  b.className=bp>=0?'pl-pos':'pl-neg';
  $('sb-warn').textContent = n>11 ? ' (more than an XI)' : '';
}
function clearSel(){
  document.querySelectorAll('.sel:checked').forEach(c=>{c.checked=false;c.closest('tr').classList.remove('selrow');});
  recalc();
}

const STATIC = {{ 'true' if static else 'false' }};
const money=v=>(v>=0?'+':'')+'£'+Number(v).toFixed(1)+'m';
const plClass=v=>v>=0?'pl-pos':'pl-neg';

async function saveSale(inp){
  const price=inp.value.trim();
  if(STATIC){ saveLocal(inp, price); return; }   // shared snapshot: recompute in-browser, no server
  const player=inp.dataset.player;
  inp.disabled=true;
  try{
    const res=await fetch('/api/sale',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({player,price})});
    const d=await res.json();
    if(!res.ok){ alert(d.error||'Save failed'); return; }
    applyRow(inp, d.row); applyTotals(d.totals);
  }catch(e){ alert('Save failed: '+e); }
  finally{ inp.disabled=false; }
}

function saveLocal(inp, price){
  const nbv=+inp.dataset.nbv, market=+inp.dataset.market;
  if(price && (isNaN(+price) || +price<0)){ inp.value=''; price=''; }
  const sold = price!=='';
  const proceeds = sold ? +price : market;
  applyRow(inp, {player:inp.dataset.player, sold:sold,
    sale_price_gbp_m: sold?+(+price).toFixed(1):'', book_profit_gbp_m:+(proceeds-nbv).toFixed(1),
    market_value_gbp_m:market, nbv_gbp_m:nbv});
  recomputeTotals();
}

function recomputeTotals(){
  let bp=0, realized=0, unrealized=0;
  document.querySelectorAll('#t tbody tr').forEach(tr=>{
    if(!tr.querySelector('.sel')) return;            // skip loaned-in (no checkbox)
    const v=+tr.cells[8].dataset.v;                  // book P/L
    bp+=v;
    const inp=tr.querySelector('.saleinp');
    if(inp && inp.value.trim()!=='') realized+=v; else unrealized+=v;
  });
  applyTotals({bp:+bp.toFixed(1), realized:+realized.toFixed(1), unrealized:+unrealized.toFixed(1)});
}

function applyRow(inp, row){
  const tr=inp.closest('tr'), sold=row.sold;
  inp.classList.toggle('has', sold);
  inp.value = sold ? row.sale_price_gbp_m : '';
  tr.cells[7].dataset.v = sold ? row.sale_price_gbp_m : -1;          // sale price (sort)
  const pl=tr.cells[8];                                              // book P/L
  pl.dataset.v=row.book_profit_gbp_m; pl.textContent=money(row.book_profit_gbp_m);
  pl.className=plClass(row.book_profit_gbp_m);
  const pcell=tr.cells[1];                                           // SOLD badge
  let badge=pcell.querySelector('.b-sold');
  if(sold){
    if(!badge){ badge=document.createElement('span'); badge.className='badge b-sold';
      pcell.insertBefore(badge, pcell.childNodes[1]||null); }
    badge.textContent='SOLD £'+row.sale_price_gbp_m+'m';
  } else if(badge){ badge.remove(); }
  const cb=tr.querySelector('.sel');                                 // simulator data
  if(cb){ cb.dataset.bp=row.book_profit_gbp_m;
    cb.dataset.mv = sold ? row.sale_price_gbp_m : row.market_value_gbp_m;
    if(cb.checked) recalc(); }
}

function applyTotals(t){
  const set=(id,v)=>{ const el=$(id); el.textContent='£'+Number(v).toFixed(1)+'m'; el.className='val '+plClass(v); };
  set('card-bp',t.bp); set('card-real',t.realized); set('card-unreal',t.unrealized);
  realizedNow=t.realized; updatePSR();
}

// ---- PSR / FFP headroom (client-side scenario; inputs saved to localStorage) ----
let realizedNow = {{ t.realized }};
function updatePSR(){
  const limit=parseFloat($('psr-limit').value)||0;
  const loss=parseFloat($('psr-loss').value)||0;
  const headroom = limit - loss + realizedNow;       // room before breaching the limit
  $('psr-realized').textContent='£'+realizedNow.toFixed(1)+'m';
  const h=$('psr-headroom');
  h.textContent=(headroom<0?'-£':'£')+Math.abs(headroom).toFixed(1)+'m';
  h.className='val '+plClass(headroom);
  $('psr-status').textContent = headroom>=0 ? 'within limit' : 'OVER limit — breach';
  const pct = limit>0 ? Math.max(0,Math.min(100, realizedNow/limit*100)) : 0;
  $('psr-bar').style.width=pct+'%';
  $('psr-claw').textContent =
    'Sales claw back £'+realizedNow.toFixed(1)+'m = '+pct.toFixed(0)+'% of the £'+limit.toFixed(0)+'m limit'
    +' · net headroom = limit − assumed loss + realized sale profit.';
  localStorage.setItem('psr', JSON.stringify({limit:$('psr-limit').value, loss:$('psr-loss').value}));
}
(function initPSR(){
  try{ const s=JSON.parse(localStorage.getItem('psr')||'{}');
    if(s.limit!==undefined) $('psr-limit').value=s.limit;
    if(s.loss!==undefined) $('psr-loss').value=s.loss;
  }catch(e){}
  updatePSR();
})();

// ---- Shareable scenarios (state encoded in the URL ?s= param) ----
let toastT;
function flash(msg){ const t=$('toast'); t.textContent=msg; t.classList.add('show');
  clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove('show'),2200); }

function buildScenario(){
  const sales={};
  document.querySelectorAll('.saleinp').forEach(inp=>{ const v=inp.value.trim(); if(v!=='') sales[inp.dataset.player]=+v; });
  const sel=[...document.querySelectorAll('.sel:checked')].map(cb=>cb.closest('tr').querySelector('.saleinp').dataset.player);
  return {sales, sel};
}
function shareScenario(){
  const enc=btoa(unescape(encodeURIComponent(JSON.stringify(buildScenario()))));
  const url=location.origin+location.pathname+'?s='+encodeURIComponent(enc);
  history.replaceState(null,'',url);
  if(navigator.clipboard) navigator.clipboard.writeText(url).then(()=>flash('Scenario link copied to clipboard!'),()=>prompt('Copy your link:',url));
  else prompt('Copy your scenario link:',url);
}
async function clearSalesQuiet(){
  const inputs=[...document.querySelectorAll('.saleinp')].filter(i=>i.value.trim()!=='');
  for(const inp of inputs){ inp.value=''; await saveSale(inp); }
}
async function clearSales(){
  await clearSalesQuiet();
  if(STATIC) history.replaceState(null,'',location.origin+location.pathname);
  flash('Sale prices cleared');
}
async function resetAll(){
  if(!STATIC && !confirm('Reset all sale prices (clears them in players.csv), Sell XI selections and the PSR panel to defaults?')) return;
  await clearSalesQuiet();
  document.querySelectorAll('.sel:checked').forEach(c=>{ c.checked=false; c.closest('tr').classList.remove('selrow'); });
  recalc();
  $('psr-limit').value=105; $('psr-loss').value=0; updatePSR();
  if(STATIC) history.replaceState(null,'',location.origin+location.pathname);
  flash('Everything reset to defaults');
}
function applyScenario(scn){
  if(scn.sales) document.querySelectorAll('.saleinp').forEach(inp=>{
    const p=inp.dataset.player;
    if(Object.prototype.hasOwnProperty.call(scn.sales,p)){ inp.value=scn.sales[p]; saveLocal(inp, String(scn.sales[p])); }
  });
  if(scn.sel){ scn.sel.forEach(p=>{
    const inp=[...document.querySelectorAll('.saleinp')].find(i=>i.dataset.player===p);
    const cb=inp&&inp.closest('tr').querySelector('.sel');
    if(cb&&!cb.checked){ cb.checked=true; cb.closest('tr').classList.add('selrow'); } });
    recalc(); }
}
(function loadScenario(){
  const enc=new URLSearchParams(location.search).get('s'); if(!enc) return;
  try{ applyScenario(JSON.parse(decodeURIComponent(escape(atob(enc))))); flash('Loaded shared scenario'); }catch(e){}
})();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    rows = bv.load_players()
    totals = bv.compute_totals(rows)
    return render_template_string(
        PAGE, rows=rows, t=totals, today=bv.TODAY, rate=bv.EUR_GBP, static=PUBLIC
    )


@app.route("/api/sale", methods=["POST"])
def api_sale():
    if PUBLIC:  # read-only public deployment — no server-side writes
        return jsonify(error="Editing is disabled on the public site"), 403
    data = request.get_json(force=True)
    player = (data.get("player") or "").strip()
    price = (str(data.get("price") or "")).strip()
    if price:  # validate numeric, else reject (empty = clear the sale)
        try:
            if float(price) < 0:
                raise ValueError
        except ValueError:
            return jsonify(error="Sale price must be a number ≥ 0"), 400
    try:
        bv.set_sale_price(player, price)
    except KeyError:
        return jsonify(error=f"Unknown player '{player}'"), 404
    except ValueError as e:
        return jsonify(error=str(e)), 400

    rows = bv.load_players()
    totals = bv.compute_totals(rows)
    row = next((r for r in rows if r["player"] == player), None)
    return jsonify(row=row, totals=totals)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5200)), debug=True)
