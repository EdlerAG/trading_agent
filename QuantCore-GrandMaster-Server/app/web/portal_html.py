PORTAL_HTML: str = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>QuantCore V58.0 Pure SOTA | Sovereign Multi-Asset Terminal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{
  --bg0:#050811;--bg1:#0b1120;--card:rgba(15,23,42,0.82);--border:rgba(56,189,248,0.18);
  --text:#f8fafc;--muted:#94a3b8;--emerald:#10b981;--sky:#38bdf8;--amber:#f59e0b;--rose:#ef4444;--violet:#8b5cf6;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:radial-gradient(circle at 12% 8%,#0f172a 0%,#050811 100%);
  color:var(--text);font-family:'Plus Jakarta Sans',sans-serif;min-height:100vh;padding:16px 22px;
}
.mono{font-family:'JetBrains Mono',monospace}
.wrap{max-width:1620px;margin:0 auto}

/* Top Institutional Bar */
.top-bar{
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;
  background:var(--card);backdrop-filter:blur(16px);border:1px solid var(--border);
  border-radius:16px;padding:14px 22px;margin-bottom:18px;box-shadow:0 10px 35px rgba(0,0,0,0.5);
}
.brand{display:flex;align-items:center;gap:12px}
.brand-logo{
  width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#10b981,#0284c7);
  display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:800;box-shadow:0 0 18px rgba(16,185,129,0.4);
}
.pulse{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}
.pulse.on{background:var(--emerald);box-shadow:0 0 10px var(--emerald);animation:pulseAnim 2s infinite}
.pulse.warn{background:var(--amber);box-shadow:0 0 10px var(--amber)}
@keyframes pulseAnim{0%{transform:scale(0.95)}50%{transform:scale(1.18)}100%{transform:scale(0.95)}}

.top-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.btn{
  background:#1e293b;color:#f8fafc;border:1px solid rgba(255,255,255,0.1);padding:8px 14px;
  border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;transition:all 0.18s;display:inline-flex;align-items:center;gap:6px;
}
.btn:hover{border-color:var(--sky);background:#26354d}
.btn:active{transform:scale(0.97)}
.btn-emerald{background:rgba(16,185,129,0.18);border-color:var(--emerald);color:#34d399}
.btn-sky{background:rgba(56,189,248,0.18);border-color:var(--sky);color:#7dd3fc}
.btn-amber{background:rgba(245,158,11,0.18);border-color:var(--amber);color:#fcd34d}
.btn-rose{background:rgba(239,68,68,0.18);border-color:var(--rose);color:#fca5a5}

select,input[type="number"],input[type="password"]{
  background:#090d16;color:#f8fafc;border:1px solid #334155;padding:7px 11px;border-radius:9px;
  font-size:13px;font-family:'JetBrains Mono',monospace;outline:none;
}
select:focus,input:focus{border-color:var(--sky)}

/* KPI Grid */
.kpi-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:18px}
@media(max-width:1280px){.kpi-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:720px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
.kpi-card{
  background:var(--card);border:1px solid rgba(255,255,255,0.07);border-radius:14px;padding:15px 18px;
  box-shadow:0 6px 24px rgba(0,0,0,0.35);
}
.kpi-title{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px}
.kpi-val{font-size:23px;font-weight:800;font-family:'JetBrains Mono',monospace;color:#fff}
.kpi-sub{font-size:12px;margin-top:5px;font-family:'JetBrains Mono',monospace;color:var(--muted)}

/* Bento Cards */
.bento-card{
  background:linear-gradient(145deg,rgba(15,23,42,0.92) 0%,rgba(17,28,53,0.72) 100%);
  border:1px solid var(--border);border-radius:16px;padding:18px 20px;margin-bottom:18px;
  box-shadow:0 10px 30px rgba(0,0,0,0.45);
}
.card-hdr{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.card-title{font-size:15px;font-weight:800;color:var(--sky);text-transform:uppercase;letter-spacing:0.6px}

/* 5-Currency Matrix Grid */
.coins-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
@media(max-width:1360px){.coins-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:860px){.coins-grid{grid-template-columns:1fr}}
.coin-card{
  background:rgba(9,13,22,0.78);border:1px solid rgba(255,255,255,0.09);border-radius:14px;padding:14px;
  display:flex;flex-direction:column;justify-content:space-between;transition:border 0.2s;
}
.coin-card.active-pos{border-color:rgba(16,185,129,0.55);box-shadow:0 0 20px rgba(16,185,129,0.12)}
.coin-card.disabled-coin{opacity:0.58;border-color:rgba(100,116,139,0.2)}
.coin-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.coin-sym{font-size:17px;font-weight:800;font-family:'JetBrains Mono',monospace}
.coin-price{font-size:14px;color:var(--sky);font-family:'JetBrains Mono',monospace;font-weight:700}
.phase-badge{
  display:inline-block;padding:4px 9px;border-radius:7px;font-size:11px;font-weight:700;
  font-family:'JetBrains Mono',monospace;margin-bottom:10px;
}
.ph-0{background:rgba(148,163,184,0.15);color:#cbd5e1;border:1px solid #475569}
.ph-1{background:rgba(245,158,11,0.15);color:#fcd34d;border:1px solid #d97706}
.ph-2{background:rgba(16,185,129,0.18);color:#34d399;border:1px solid #059669}
.ph-3{background:rgba(139,92,246,0.22);color:#c4b5fd;border:1px solid #7c3aed}
.ph--1{background:rgba(239,68,68,0.18);color:#fca5a5;border:1px solid #dc2626}

.coin-metrics{font-size:12px;line-height:1.65;color:#cbd5e1;margin-bottom:10px}
.coin-metrics b{color:#fff;font-family:'JetBrains Mono',monospace}
.bar-bg{width:100%;height:6px;background:#1e293b;border-radius:4px;overflow:hidden;margin:6px 0 10px 0}
.bar-fill{height:100%;background:linear-gradient(90deg,#0284c7,#10b981);transition:width 0.3s}
.coin-controls{border-top:1px solid rgba(255,255,255,0.07);padding-top:10px;display:flex;gap:6px;align-items:center}

/* Two-column layout */
.split-2{display:grid;grid-template-columns:1.65fr 1fr;gap:18px}
@media(max-width:1180px){.split-2{grid-template-columns:1fr}}

/* Tables & Logs */
.tbl-wrap{overflow-x:auto;max-height:340px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px;text-align:left}
th{position:sticky;top:0;background:#0f172a;color:var(--muted);padding:9px 10px;border-bottom:1px solid #334155}
td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.05);font-family:'JetBrains Mono',monospace}
.log-box{
  background:#060911;border:1px solid #1e293b;border-radius:11px;padding:12px;
  font-family:'JetBrains Mono',monospace;font-size:11.5px;color:#94a3b8;max-height:260px;overflow-y:auto;white-space:pre-wrap;
}

/* Login Overlay */
#loginModal{
  position:fixed;inset:0;background:rgba(5,8,17,0.92);backdrop-filter:blur(12px);
  display:none;align-items:center;justify-content:center;z-index:999;
}
.login-box{
  background:#0f172a;border:1px solid var(--sky);border-radius:18px;padding:30px;width:360px;text-align:center;
  box-shadow:0 20px 50px rgba(0,0,0,0.8);
}
.toast{
  position:fixed;bottom:22px;right:22px;background:#10b981;color:#04130d;padding:12px 22px;
  border-radius:12px;font-weight:800;font-size:13.5px;display:none;z-index:1000;box-shadow:0 10px 25px rgba(0,0,0,0.5);
}
</style>
</head>
<body>

<div id="loginModal">
  <div class="login-box">
    <div style="font-size:40px;margin-bottom:8px">👑</div>
    <h2 style="margin-bottom:4px">QUANTCORE V58.0 PURE SOTA</h2>
    <p style="font-size:12.5px;color:#94a3b8;margin-bottom:18px">Sovereign Multi-Asset Institutional Terminal</p>
    <input type="password" id="loginPass" placeholder="Введіть пароль термінала..." style="width:100%;margin-bottom:12px;padding:11px">
    <button class="btn btn-sky" style="width:100%;justify-content:center;padding:11px" onclick="doLogin()">🔓 Авторизувати термінал</button>
  </div>
</div>

<div class="wrap">
  <!-- TOP STATUS BAR -->
  <div class="top-bar">
    <div class="brand">
      <div class="brand-logo">⚡</div>
      <div>
        <div style="display:flex;align-items:center;gap:8px">
          <span id="statusDot" class="pulse on"></span>
          <span id="statusText" style="font-weight:800;font-size:14.5px">ONLINE (V58.0 PURE SOTA)</span>
          <span style="color:#475569">|</span>
          <span class="mono" style="font-size:12.5px;color:var(--sky)" id="cartridgeBadge">Cartridge: loading...</span>
        </div>
        <div class="mono" style="font-size:11.5px;color:var(--muted);margin-top:3px">
          RAM: <b id="ramBadge" style="color:#10b981">-- MB</b> / 420 MB &nbsp;|&nbsp;
          Диск: <b id="diskBadge">-- MB</b> &nbsp;|&nbsp;
          Свічка: <span id="candleBadge">--</span> UTC
        </div>
      </div>
    </div>

    <div class="top-actions">
      <select id="riskSelect" onchange="changeRiskProfile()" title="Профіль плеча портфеля">
        <option value="CONSERVATIVE">🛡️ Conservative (1.6x)</option>
        <option value="OPTIMAL">⚖️ Optimal (2.4x | Calmar 10.35)</option>
        <option value="AGGRESSIVE">🔥 Aggressive (3.2x)</option>
        <option value="OVERDRIVE">🚀 Overdrive (3.5x | +264.8%)</option>
      </select>
      <select id="orchModeSelect" onchange="changeRiskProfile()" title="Режим взаємодії ядер">
        <option value="PORTFOLIO_SYNERGY">🤝 Portfolio Synergy (Waterfall)</option>
        <option value="SOLO_MAX">🎯 Solo Max (Individual)</option>
      </select>
      <button class="btn btn-sky" onclick="triggerWakeup()">⚡ Перерахувати</button>
      <button class="btn btn-amber" id="pauseBtn" onclick="togglePause()">⏸️ Пауза</button>
      <button class="btn" onclick="restartServer()" title="Перезавантажити службу systemd без консолі">🔄 Рестарт Сервера</button>
      <button class="btn btn-rose" onclick="panicCloseAll()">🚨 PANIC USDT</button>
    </div>
  </div>

  <!-- ROW 1: 6 KPI CARDS -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-title">Сумарний Equity</div>
      <div class="kpi-val" id="kpiEquity">$0.00</div>
      <div class="kpi-sub" id="kpiPnlPct">+0.00%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Чиста Альфа vs BTC</div>
      <div class="kpi-val" id="kpiAlpha">+0.00%</div>
      <div class="kpi-sub" id="kpiBtcBh">BTC B&H: +0.00%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Експозиція / Лідер</div>
      <div class="kpi-val" id="kpiLev">0.00x</div>
      <div class="kpi-sub" id="kpiLeader">Лідер: BTCUSDT</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Sharpe / Calmar</div>
      <div class="kpi-val" id="kpiSharpe">0.00</div>
      <div class="kpi-sub" id="kpiCalmar">Calmar: 0.00</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Max Drawdown</div>
      <div class="kpi-val" id="kpiMdd" style="color:var(--rose)">0.00%</div>
      <div class="kpi-sub" id="kpiFees">Fee: $0.00</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Операцій / WinRate</div>
      <div class="kpi-val" id="kpiOps">0</div>
      <div class="kpi-sub" id="kpiWr">WR: 0.0% | Net: $0.00</div>
    </div>
  </div>

  <!-- ROW 2: 5-CURRENCY CONTROL MATRIX & LIVE RADAR -->
  <div class="bento-card">
    <div class="card-hdr">
      <span class="card-title">🎛️ Пульт керування 10 валютами та Радар Каскаду V58 (Sticky Waterfall Top-3)</span>
      <span class="mono" style="font-size:12.5px;color:var(--muted)">
        Breadth: <b id="breadthVal" style="color:#fff">0.00</b> &nbsp;|&nbsp;
        Gemini News: <b id="newsVal" style="color:var(--sky)">0.00</b>
      </span>
    </div>
    <div class="coins-grid" id="coinsGrid"></div>
  </div>

  <!-- ROW 3: PLOTLY CHARTS -->
  <div class="split-2">
    <div class="bento-card">
      <div class="card-hdr">
        <span class="card-title">📈 Крива Капіталу V58 vs Buy & Hold BTC та Просадка (Drawdown %)</span>
        <div style="display:flex;gap:6px">
          <button class="btn" style="padding:4px 9px;font-size:11.5px" onclick="loadCharts(1)">24г</button>
          <button class="btn" style="padding:4px 9px;font-size:11.5px" onclick="loadCharts(7)">7д</button>
          <button class="btn" style="padding:4px 9px;font-size:11.5px" onclick="loadCharts(30)">30д</button>
          <button class="btn" style="padding:4px 9px;font-size:11.5px" onclick="loadCharts(365)">Весь час</button>
        </div>
      </div>
      <div id="equityChart" style="width:100%;height:410px"></div>
    </div>

    <div class="bento-card">
      <div class="card-hdr">
        <span class="card-title">🧬 Розподіл Маржі та Онлайн-Довіра Сарі-Навчання (MWU)</span>
      </div>
      <div id="allocChart" style="width:100%;height:245px"></div>

      <!-- OTA CARTRIDGE HOT-SWAP BOX -->
      <div style="border-top:1px solid rgba(255,255,255,0.08);padding-top:12px;margin-top:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span style="font-size:13px;font-weight:700;color:var(--emerald)">📦 Гаряча заміна ШІ-Картриджа (.joblib Hot-Swap)</span>
          <button class="btn" style="padding:5px 10px;font-size:11.5px" onclick="rollbackCartridge()">⏪ Відкат Моделі</button>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="file" id="joblibFile" accept=".joblib" style="font-size:12px;color:#94a3b8;flex:1">
          <button class="btn btn-emerald" onclick="uploadCartridge()">🚀 Залити .joblib</button>
        </div>
      </div>
    </div>
  </div>

  <!-- ROW 4: TRADES JOURNAL & SERVER LOGS -->
  <div class="split-2">
    <div class="bento-card">
      <div class="card-hdr">
        <span class="card-title">📜 Журнал виконаних ордерів (5 Валют)</span>
        <select id="tradeSymFilter" onchange="loadTrades()" style="padding:4px 8px;font-size:12px">
          <option value="">Усі валюти</option>
          <option value="BTCUSDT">BTCUSDT</option>
          <option value="ETHUSDT">ETHUSDT</option>
          <option value="SOLUSDT">SOLUSDT</option>
          <option value="BNBUSDT">BNBUSDT</option>
          <option value="XRPUSDT">XRPUSDT</option>
        </select>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr><th>Час (UTC)</th><th>Валюта</th><th>Дія</th><th>Об'єм</th><th>Ціна</th><th>Net PnL</th><th>Примітка</th></tr>
          </thead>
          <tbody id="tradesBody"></tbody>
        </table>
      </div>
    </div>

    <div class="bento-card">
      <div class="card-hdr">
        <span class="card-title">🔬 Живий Системний Лог Сервера (trading_bot.log)</span>
        <button class="btn" style="padding:4px 10px;font-size:11.5px" onclick="loadLogs()">🔄 Оновити</button>
      </div>
      <div class="log-box" id="logBox">Завантаження логів...</div>
    </div>
  </div>
</div>

<div class="toast" id="toast">Виконано!</div>

<script>
let currentChartDays = 30;
let isPausedState = false;

function showToast(msg, isErr=false){
  const t = document.getElementById('toast');
  t.style.background = isErr ? '#ef4444' : '#10b981';
  t.style.color = isErr ? '#fff' : '#04130d';
  t.innerText = msg;
  t.style.display = 'block';
  setTimeout(()=>{ t.style.display='none'; }, 2800);
}

function getHeaders(){
  const tok = localStorage.getItem('qc_token') || '';
  return {'Content-Type':'application/json', 'X-Api-Key': tok};
}

async function apiFetch(url, opts={}){
  opts.headers = Object.assign(getHeaders(), opts.headers || {});
  const resp = await fetch(url, opts);
  if(resp.status === 401){
    document.getElementById('loginModal').style.display = 'flex';
    throw new Error('Unauthorized');
  }
  return resp.json();
}

async function doLogin(){
  const pwd = document.getElementById('loginPass').value;
  const r = await fetch('/api/v1/auth/login', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({password: pwd})
  });
  if(r.ok){
    const d = await r.json();
    localStorage.setItem('qc_token', d.token);
    document.getElementById('loginModal').style.display = 'none';
    refreshAll();
  } else {
    showToast('❌ Невірний пароль', true);
  }
}

function renderCoinsMatrix(coins){
  const grid = document.getElementById('coinsGrid');
  grid.innerHTML = '';
  coins.forEach(c => {
    const hasPos = Math.abs(c.current_pos_qty) > 0;
    const card = document.createElement('div');
    card.className = 'coin-card' + (hasPos ? ' active-pos' : '') + (!c.enabled ? ' disabled-coin' : '');

    const normScore = Math.max(0, Math.min(100, Math.round((c.alpha_score + 0.4) / 1.4 * 100)));
    const posStr = hasPos
      ? `${c.current_pos_qty > 0 ? '🟢 LONG' : '🔴 SHORT'} ${Math.abs(c.current_pos_qty).toFixed(4)} ($${c.notional_usdt.toFixed(0)})`
      : '⚪ 100% КЕШ (USDT)';
    const pnlColor = c.unrealized_pnl >= 0 ? '#10b981' : '#ef4444';
    const slStr = c.active_sl_price > 0 ? `$${c.active_sl_price.toFixed(2)} ${c.is_breakeven ? '🛡️BE' : ''}` : '—';

    card.innerHTML = `
      <div>
        <div class="coin-top">
          <span class="coin-sym">${c.symbol}</span>
          <span class="coin-price">$${c.price ? c.price.toLocaleString(undefined,{maximumFractionDigits:4}) : '--'}</span>
        </div>
        <span class="phase-badge ph-${c.phase}">${c.phase_label}</span>
        <div class="coin-metrics">
          <div>Позиція: <b>${posStr}</b></div>
          <div>Unrealized PnL: <b style="color:${pnlColor}">${c.unrealized_pnl >= 0 ? '+' : ''}${c.unrealized_pnl.toFixed(2)} USDT</b></div>
          <div>Ціль V58: <b>${c.target_weight >= 0 ? '+' : ''}${c.target_weight.toFixed(2)}x</b> | SL: <b>${slStr}</b></div>
          <div>Alpha Score: <b>${c.alpha_score >= 0 ? '+' : ''}${c.alpha_score.toFixed(3)}</b> | MWU: <b>${c.effective_weight.toFixed(2)}x</b></div>
        </div>
        <div class="bar-bg"><div class="bar-fill" style="width:${normScore}%"></div></div>
      </div>
      <div class="coin-controls">
        <select onchange="updateCoinMode('${c.symbol}', this.value)" style="flex:1;padding:5px">
          <option value="1" ${c.mode===1?'selected':''}>🟢 AUTO (L+S)</option>
          <option value="2" ${c.mode===2?'selected':''}>📈 LONG ONLY</option>
          <option value="4" ${c.mode===4?'selected':''}>🛡️ CORE ONLY</option>
          <option value="3" ${c.mode===3?'selected':''}>📉 SHORT ONLY</option>
          <option value="0" ${c.mode===0?'selected':''}>🔴 OFF (Вимк)</option>
        </select>
        <input type="number" step="0.05" min="0.2" max="3.5" value="${c.base_weight}"
               style="width:64px;padding:5px" title="Базовий пріоритет капіталу"
               onchange="updateCoinWeight('${c.symbol}', this.value)">
      </div>
    `;
    grid.appendChild(card);
  });
}

async function updateCoinMode(sym, modeVal){
  const m = parseInt(modeVal);
  await apiFetch('/api/v1/control/coin', {
    method:'POST',
    body: JSON.stringify({symbol: sym, mode: m, enabled: m !== 0})
  });
  showToast(`🎛️ ${sym}: режим оновлено!`);
  loadState();
}

async function updateCoinWeight(sym, wVal){
  await apiFetch('/api/v1/control/coin', {
    method:'POST',
    body: JSON.stringify({symbol: sym, base_weight: parseFloat(wVal)})
  });
  showToast(`⚖️ ${sym}: вагу змінено на ${wVal}x`);
  loadState();
}

async function changeRiskProfile(){
  const prof = document.getElementById('riskSelect').value;
  const om = document.getElementById('orchModeSelect').value;
  try{
    const r = await apiFetch('/api/v1/control/risk', {
      method:'POST',
      body: JSON.stringify({risk_profile: prof, orchestrator_mode: om})
    });
    if(r && r.ok){
      showToast(`⚙️ Збережено профіль: ${prof} (${om})!`);
    } else {
      showToast(`❌ Помилка: ${r?.detail || 'Відхилено'}`, true);
    }
  }catch(e){
    showToast(`❌ Помилка: ${e.message}`, true);
  }
  loadState();
}

async function triggerWakeup(){
  await apiFetch('/api/v1/control/wakeup', {method:'POST'});
  showToast('⚡ Сигнал перерахунку свічки відправлено!');
  setTimeout(refreshAll, 1500);
}

async function togglePause(){
  await apiFetch('/api/v1/control/pause', {
    method:'POST',
    body: JSON.stringify({paused: !isPausedState})
  });
  showToast(!isPausedState ? '⏸️ Торгівлю призупинено' : '▶️ Торгівлю відновлено!');
  loadState();
}

async function restartServer(){
  if(!confirm('Перезавантажити сервер QuantCore зараз? Служба systemd автоматично підніме його з оновленими файлами за 3 секунди.')) return;
  try{
    await apiFetch('/api/v1/control/restart', {method:'POST'});
    showToast('🔄 Сервер перезавантажується (3 сек)...');
    setTimeout(refreshAll, 4000);
  }catch(e){}
}

async function panicCloseAll(){
  if(!confirm('🚨 ЕКСТРЕНО ЗАКРИТИ ВСІ ПОЗИЦІЇ ПО ВСІХ 5 ВАЛЮТАХ У USDT?')) return;
  const r = await apiFetch('/api/v1/control/panic', {method:'POST'});
  showToast('🚨 Усі позиції ліквідовано в USDT!', true);
  refreshAll();
}

async function uploadCartridge(){
  const fInput = document.getElementById('joblibFile');
  if(!fInput.files.length){ showToast('Оберіть файл .joblib', true); return; }
  const fd = new FormData();
  fd.append('file', fInput.files[0]);
  showToast('⏳ Завантаження та Hot-Swap картриджа...');
  const tok = localStorage.getItem('qc_token') || '';
  const resp = await fetch('/api/v1/cartridge/upload', {
    method:'POST', headers:{'X-Api-Key': tok}, body: fd
  });
  const d = await resp.json();
  if(resp.ok && d.ok){
    showToast(`🚀 Hot-Swap виконано: ${d.active_cartridge}`);
    fInput.value = '';
    refreshAll();
  } else {
    showToast(`❌ Помилка: ${d.detail || 'Invalid file'}`, true);
  }
}

async function rollbackCartridge(){
  if(!confirm('Повернути попередній картридж моделі (.joblib)?')) return;
  const r = await apiFetch('/api/v1/cartridge/rollback', {method:'POST'});
  if(r.ok){
    showToast(`⏪ Відкат виконано: ${r.active_cartridge}`);
    refreshAll();
  }
}

async function loadState(){
  try{
    const d = await apiFetch('/api/v1/state');
    if(!d.ok) return;
    const eng = d.engine;
    const res = d.resources;
    const t = eng.telemetry || {};

    isPausedState = eng.is_paused;
    document.getElementById('statusDot').className = 'pulse ' + (isPausedState ? 'warn' : 'on');
    document.getElementById('statusText').innerText = isPausedState ? 'PAUSED (Торгівля на паузі)' : 'ONLINE (Zero-Idle Hibernation)';
    document.getElementById('pauseBtn').innerText = isPausedState ? '▶️ Старт' : '⏸️ Пауза';
    document.getElementById('cartridgeBadge').innerText = (d.cartridge && d.cartridge.active_cartridge) ? d.cartridge.active_cartridge : 'Active';
    document.getElementById('ramBadge').innerText = (res.ram_rss_mb || '--') + ' MB';
    document.getElementById('diskBadge').innerText = (res.storage_used_mb || '--') + ' MB';
    document.getElementById('candleBadge').innerText = t.timestamp || eng.last_candle_ts || '--';

    if(eng && eng.risk_profile) document.getElementById('riskSelect').value = eng.risk_profile;
    if(eng && eng.orchestrator_mode) document.getElementById('orchModeSelect').value = eng.orchestrator_mode;

    document.getElementById('kpiLev').innerText = (t.gross_leverage || 0).toFixed(2) + 'x';
    document.getElementById('kpiLeader').innerText = 'Лідер: ' + (t.top_leader || 'BTCUSDT');
    document.getElementById('breadthVal').innerText = (t.market_breadth || 0).toFixed(2);
    document.getElementById('newsVal').innerText = (t.news_sentiment || 0).toFixed(2);

    renderCoinsMatrix(eng.coins || []);

    const syms = (eng.coins || []).map(c => c.symbol);
    const weights = (eng.coins || []).map(c => c.target_weight);
    const mwu = (eng.coins || []).map(c => c.effective_weight);

    Plotly.react('allocChart', [
      {x: syms, y: weights, name: 'Цільова Позиція (x)', type: 'bar', marker: {color: '#10b981'}},
      {x: syms, y: mwu, name: 'MWU Довіра (x)', type: 'bar', marker: {color: '#38bdf8'}}
    ], {
      paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(9,13,22,0.6)',
      font:{color:'#cbd5e1', family:'JetBrains Mono', size:11},
      margin:{l:35,r:15,t:10,b:30}, barmode:'group',
      legend:{orientation:'h', y:1.15},
      xaxis:{gridcolor:'#1e293b'}, yaxis:{gridcolor:'#1e293b'}
    }, {displayModeBar:false, responsive:true});
  }catch(e){}
}

async function loadCharts(days){
  if(days) currentChartDays = days;
  try{
    const d = await apiFetch('/api/v1/equity?days=' + currentChartDays);
    if(!d.ok || !d.kpis) return;
    const k = d.kpis;
    const ch = d.chart;

    if(k.latest_equity !== undefined){
      document.getElementById('kpiEquity').innerText = '$' + k.latest_equity.toLocaleString(undefined,{minimumFractionDigits:2});
      document.getElementById('kpiPnlPct').innerText = (k.total_pnl_pct>=0?'+':'') + k.total_pnl_pct.toFixed(2) + '%';
      document.getElementById('kpiPnlPct').style.color = k.total_pnl_pct>=0 ? '#10b981' : '#ef4444';
      document.getElementById('kpiAlpha').innerText = (k.alpha_vs_btc_pct>=0?'+':'') + k.alpha_vs_btc_pct.toFixed(2) + '%';
      document.getElementById('kpiBtcBh').innerText = 'BTC B&H: ' + (k.btc_bh_pct>=0?'+':'') + k.btc_bh_pct.toFixed(2) + '%';
      document.getElementById('kpiSharpe').innerText = k.sharpe_ratio.toFixed(2);
      document.getElementById('kpiCalmar').innerText = 'Calmar: ' + k.calmar_ratio.toFixed(2);
      document.getElementById('kpiMdd').innerText = k.max_drawdown_pct.toFixed(2) + '%';
      document.getElementById('kpiFees').innerText = 'Fee: $' + k.total_fees_usdt.toFixed(2);
      document.getElementById('kpiOps').innerText = k.total_ops;
      document.getElementById('kpiWr').innerText = `WR: ${k.win_rate_pct.toFixed(1)}% | Net: $${k.net_realized_pnl.toFixed(1)}`;
    }

    if(ch && ch.times && ch.times.length > 0){
      Plotly.react('equityChart', [
        {x: ch.times, y: ch.equity_ret_pct, name:'QuantCore V58.0 (%)', type:'scatter', mode:'lines', line:{color:'#10b981', width:2.5}, yaxis:'y1'},
        {x: ch.times, y: ch.btc_ret_pct, name:'Buy & Hold BTC (%)', type:'scatter', mode:'lines', line:{color:'#f59e0b', width:1.5, dash:'dot'}, yaxis:'y1'},
        {x: ch.times, y: ch.drawdown_pct, name:'Drawdown (%)', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(239,68,68,0.16)', line:{color:'#ef4444', width:1.2}, yaxis:'y2'}
      ], {
        paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(9,13,22,0.6)',
        font:{color:'#cbd5e1', family:'JetBrains Mono', size:11},
        margin:{l:45,r:15,t:10,b:30}, hovermode:'x unified',
        legend:{orientation:'h', y:1.12},
        xaxis:{gridcolor:'#1e293b'},
        yaxis:{domain:[0.32, 1.0], gridcolor:'#1e293b', title:'Return %'},
        yaxis2:{domain:[0.0, 0.25], gridcolor:'#1e293b', title:'DD %'}
      }, {displayModeBar:false, responsive:true});
    }
  }catch(e){}
}

async function loadTrades(){
  try{
    const sym = document.getElementById('tradeSymFilter').value;
    const d = await apiFetch('/api/v1/trades?limit=40&symbol=' + sym);
    const tb = document.getElementById('tradesBody');
    tb.innerHTML = '';
    (d.trades || []).forEach(t => {
      const tr = document.createElement('tr');
      const sCol = t.side === 'BUY' ? '#10b981' : '#ef4444';
      const pCol = t.net_pnl >= 0 ? '#10b981' : '#ef4444';
      tr.innerHTML = `
        <td>${t.time}</td>
        <td><b>${t.symbol}</b></td>
        <td style="color:${sCol};font-weight:700">${t.side}</td>
        <td>${t.amount}</td>
        <td>$${t.price.toLocaleString()}</td>
        <td style="color:${pCol};font-weight:700">${t.net_pnl>=0?'+':''}$${t.net_pnl.toFixed(2)}</td>
        <td style="color:#94a3b8">${t.note}</td>
      `;
      tb.appendChild(tr);
    });
  }catch(e){}
}

async function loadLogs(){
  try{
    const d = await apiFetch('/api/v1/logs?lines=35');
    if(d.ok){
      const box = document.getElementById('logBox');
      box.innerText = (d.lines || []).join('\n');
      box.scrollTop = box.scrollHeight;
    }
  }catch(e){}
}

function refreshAll(){
  loadState();
  loadCharts();
  loadTrades();
  loadLogs();
}

refreshAll();
setInterval(loadState, 8000);
setInterval(loadLogs, 15000);
</script>
</body>
</html>
"""