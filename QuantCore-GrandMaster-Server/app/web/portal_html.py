PORTAL_HTML: str = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>QuantCore V5.0 All-Regime Sovereign Terminal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{
  --bg0:#03060e;--bg1:#080e1e;--card:rgba(11,18,35,0.86);--card-hi:rgba(16,26,49,0.94);
  --border:rgba(56,189,248,0.16);--border-hi:rgba(56,189,248,0.42);
  --text:#f8fafc;--muted:#94a3b8;--dim:#64748b;
  --emerald:#10b981;--sky:#38bdf8;--amber:#f59e0b;--rose:#ef4444;--violet:#8b5cf6;--cyan:#06b6d4;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:
    radial-gradient(ellipse 85% 50% at 12% -12%, rgba(16,185,129,0.15), transparent),
    radial-gradient(ellipse 75% 45% at 88% 4%, rgba(56,189,248,0.13), transparent),
    radial-gradient(ellipse 60% 40% at 50% 105%, rgba(139,92,246,0.09), transparent),
    linear-gradient(180deg, #050915 0%, #03060e 100%);
  color:var(--text);font-family:'Plus Jakarta Sans',sans-serif;min-height:100vh;padding:15px 18px 36px;
  font-variant-numeric:tabular-nums;
}
.mono{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums}
.wrap{max-width:1720px;margin:0 auto}

::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:#060a14}
::-webkit-scrollbar-thumb{background:#1e293b;border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:#334155}

/* Top Institutional Command Bar */
.top-bar{
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;
  background:linear-gradient(135deg,rgba(13,21,42,0.92),rgba(8,13,26,0.88));
  backdrop-filter:blur(22px);border:1px solid var(--border);
  border-radius:18px;padding:14px 20px;margin-bottom:14px;
  box-shadow:0 16px 44px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.06);
}
.brand{display:flex;align-items:center;gap:14px}
.brand-logo{
  width:44px;height:44px;border-radius:13px;
  background:linear-gradient(135deg,#10b981 0%,#0284c7 55%,#7c3aed 100%);
  display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:800;
  box-shadow:0 0 26px rgba(16,185,129,0.42);
}
.pulse{width:9px;height:9px;border-radius:50%;display:inline-block}
.pulse.on{background:var(--emerald);box-shadow:0 0 11px var(--emerald);animation:pulseAnim 2s infinite}
.pulse.warn{background:var(--amber);box-shadow:0 0 11px var(--amber)}
@keyframes pulseAnim{0%{transform:scale(0.92);opacity:0.85}50%{transform:scale(1.25);opacity:1}100%{transform:scale(0.92);opacity:0.85}}

.pill{
  display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;
  font-size:11px;font-weight:700;font-family:'JetBrains Mono',monospace;letter-spacing:0.25px;
}
.pill-demo{background:rgba(245,158,11,0.16);color:#fbbf24;border:1px solid rgba(245,158,11,0.42)}
.pill-live{background:rgba(239,68,68,0.20);color:#fca5a5;border:1px solid rgba(239,68,68,0.5)}
.pill-eng{background:rgba(56,189,248,0.15);color:#7dd3fc;border:1px solid rgba(56,189,248,0.36)}
.pill-tier{background:rgba(139,92,246,0.18);color:#ddd6fe;border:1px solid rgba(139,92,246,0.42)}
.pill-bull{background:rgba(16,185,129,0.16);color:#34d399;border:1px solid rgba(16,185,129,0.42)}
.pill-bear{background:rgba(239,68,68,0.16);color:#fca5a5;border:1px solid rgba(239,68,68,0.42)}
.pill-chop{background:rgba(6,182,212,0.16);color:#67e8f9;border:1px solid rgba(6,182,212,0.42)}

.top-actions{display:flex;align-items:center;flex-wrap:wrap;gap:7px}
.btn{
  background:rgba(24,35,54,0.88);color:#f8fafc;border:1px solid rgba(255,255,255,0.10);padding:7px 12px;
  border-radius:10px;font-size:12px;font-weight:700;cursor:pointer;transition:all 0.16s;
  display:inline-flex;align-items:center;gap:5px;text-decoration:none;
}
.btn:hover{border-color:var(--sky);background:#22324c;transform:translateY(-1px)}
.btn:active{transform:scale(0.98)}
.btn-emerald{background:rgba(16,185,129,0.16);border-color:rgba(16,185,129,0.55);color:#34d399}
.btn-emerald:hover{background:rgba(16,185,129,0.28);border-color:#10b981}
.btn-sky{background:rgba(56,189,248,0.16);border-color:rgba(56,189,248,0.55);color:#7dd3fc}
.btn-sky:hover{background:rgba(56,189,248,0.28);border-color:#38bdf8}
.btn-violet{background:rgba(139,92,246,0.18);border-color:rgba(139,92,246,0.55);color:#ddd6fe}
.btn-amber{background:rgba(245,158,11,0.16);border-color:rgba(245,158,11,0.55);color:#fcd34d}
.btn-rose{background:rgba(239,68,68,0.16);border-color:rgba(239,68,68,0.55);color:#fca5a5}

select,input[type="number"],input[type="password"],input[type="text"]{
  background:#060a14;color:#f8fafc;border:1px solid #283548;padding:7px 10px;border-radius:9px;
  font-size:12px;font-family:'JetBrains Mono',monospace;outline:none;transition:border 0.15s;
}
select:focus,input:focus{border-color:var(--sky)}

/* 8-Card Executive KPI Ribbon */
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin-bottom:12px}
@media(min-width:1440px){.kpi-grid{grid-template-columns:repeat(8,1fr)}}
@media(max-width:760px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
.kpi-card{
  background:linear-gradient(160deg, rgba(14,22,42,0.94) 0%, rgba(8,13,27,0.86) 100%);
  border:1px solid rgba(255,255,255,0.075);border-radius:14px;padding:12px 14px;
  box-shadow:0 8px 24px rgba(0,0,0,0.38);position:relative;overflow:hidden;
}
.kpi-card::before{
  content:"";position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,rgba(56,189,248,0.5),transparent);
}
.kpi-title{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:0.55px;margin-bottom:5px;font-weight:700}
.kpi-val{font-size:19.5px;font-weight:800;font-family:'JetBrains Mono',monospace;color:#fff;line-height:1.15}
.kpi-sub{font-size:11px;margin-top:5px;font-family:'JetBrains Mono',monospace;color:var(--muted)}

/* 4-Engine All-Regime Power Strip */
.eng-strip{
  display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin-bottom:14px;
}
@media(max-width:980px){.eng-strip{grid-template-columns:repeat(2,1fr)}}
.eng-box{
  background:rgba(9,15,30,0.88);border:1px solid rgba(56,189,248,0.14);border-radius:12px;
  padding:10px 13px;display:flex;flex-direction:column;gap:5px;
}
.eng-top{display:flex;justify-content:space-between;align-items:center;font-size:11.5px;font-weight:700}
.eng-meter{width:100%;height:6px;background:#111a2e;border-radius:999px;overflow:hidden}
.eng-fill{height:100%;border-radius:999px;transition:width 0.35s ease}

/* Bento Cards */
.bento-card{
  background:linear-gradient(150deg,rgba(13,21,40,0.93) 0%,rgba(8,13,26,0.86) 100%);
  border:1px solid var(--border);border-radius:16px;padding:15px 17px;margin-bottom:15px;
  box-shadow:0 12px 32px rgba(0,0,0,0.45);
}
.card-hdr{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:9px;margin-bottom:12px}
.card-title{font-size:13px;font-weight:800;color:var(--sky);text-transform:uppercase;letter-spacing:0.6px;display:flex;align-items:center;gap:7px}

.filter-bar{display:flex;align-items:center;flex-wrap:wrap;gap:6px}
.tab-btn{
  background:#0a1120;color:var(--muted);border:1px solid #1e293b;padding:5px 10px;
  border-radius:8px;font-size:11.5px;font-weight:700;cursor:pointer;font-family:'JetBrains Mono',monospace;
}
.tab-btn.active{background:rgba(56,189,248,0.18);color:#7dd3fc;border-color:var(--sky)}

/* 58-Currency Matrix Grid */
.coins-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(252px,1fr));gap:10px;
  max-height:560px;overflow-y:auto;padding-right:4px;
}
.coin-card{
  background:rgba(6,10,20,0.86);border:1px solid rgba(255,255,255,0.075);border-radius:13px;padding:11px 13px;
  display:flex;flex-direction:column;justify-content:space-between;transition:all 0.18s;
}
.coin-card:hover{border-color:rgba(56,189,248,0.38);transform:translateY(-1px)}
.coin-card.pos-long{border-color:rgba(16,185,129,0.58);box-shadow:0 0 18px rgba(16,185,129,0.11)}
.coin-card.pos-short{border-color:rgba(239,68,68,0.58);box-shadow:0 0 18px rgba(239,68,68,0.11)}
.coin-card.disabled-coin{opacity:0.5;border-color:rgba(100,116,139,0.18)}
.coin-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px}
.coin-sym{font-size:14.5px;font-weight:800;font-family:'JetBrains Mono',monospace;display:flex;align-items:center;gap:6px}
.coin-price{font-size:12.5px;color:var(--sky);font-family:'JetBrains Mono',monospace;font-weight:700}

.sleeve-tag{font-size:10px;padding:2px 6px;border-radius:5px;font-family:'JetBrains Mono',monospace;font-weight:700}
.slv-A{background:rgba(245,158,11,0.18);color:#fcd34d;border:1px solid rgba(245,158,11,0.4)}
.slv-B{background:rgba(56,189,248,0.16);color:#7dd3fc;border:1px solid rgba(56,189,248,0.35)}
.slv-AB{background:rgba(139,92,246,0.22);color:#ddd6fe;border:1px solid rgba(139,92,246,0.45)}

.phase-badge{
  display:inline-block;padding:2px 7px;border-radius:6px;font-size:10px;font-weight:700;
  font-family:'JetBrains Mono',monospace;margin-bottom:6px;
}
.ph-0{background:rgba(148,163,184,0.12);color:#94a3b8;border:1px solid #334155}
.ph-1{background:rgba(245,158,11,0.14);color:#fcd34d;border:1px solid #b45309}
.ph-2{background:rgba(16,185,129,0.16);color:#34d399;border:1px solid #059669}
.ph-3{background:rgba(139,92,246,0.20);color:#c4b5fd;border:1px solid #7c3aed}
.ph--1{background:rgba(239,68,68,0.16);color:#fca5a5;border:1px solid #dc2626}

.factor-row{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 7px}
.f-chip{
  font-size:10px;font-family:'JetBrains Mono',monospace;padding:2px 5px;border-radius:4px;
  background:#0d1527;border:1px solid #1e293b;color:#cbd5e1;
}
.coin-metrics{font-size:11.5px;line-height:1.52;color:#cbd5e1;margin-bottom:7px}
.coin-metrics b{color:#fff;font-family:'JetBrains Mono',monospace}
.bar-bg{width:100%;height:5px;background:#141e32;border-radius:4px;overflow:hidden;margin:4px 0 8px}
.bar-fill{height:100%;background:linear-gradient(90deg,#0284c7,#10b981);transition:width 0.3s}
.coin-controls{border-top:1px solid rgba(255,255,255,0.06);padding-top:7px;display:flex;gap:5px;align-items:center}

.split-2{display:grid;grid-template-columns:1.45fr 1.05fr;gap:15px}
.split-3{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:15px}
@media(max-width:1240px){.split-2,.split-3{grid-template-columns:1fr}}

.tbl-wrap{overflow-x:auto;max-height:310px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}
th{position:sticky;top:0;background:#0a1224;color:var(--muted);padding:8px 9px;border-bottom:1px solid #283548;font-size:10.5px;text-transform:uppercase;z-index:2}
td{padding:7px 9px;border-bottom:1px solid rgba(255,255,255,0.045);font-family:'JetBrains Mono',monospace}
tr:hover td{background:rgba(56,189,248,0.045)}

.news-list{list-style:none;display:flex;flex-direction:column;gap:6px;max-height:190px;overflow-y:auto}
.news-item{
  background:rgba(6,10,20,0.75);border-left:3px solid var(--sky);padding:6px 10px;
  border-radius:0 8px 8px 0;font-size:11.5px;color:#e2e8f0;line-height:1.38;
}
.log-box{
  background:#040710;border:1px solid #1e293b;border-radius:11px;padding:11px;
  font-family:'JetBrains Mono',monospace;font-size:11px;color:#94a3b8;max-height:265px;overflow-y:auto;white-space:pre-wrap;
}

#loginModal{
  position:fixed;inset:0;background:rgba(3,6,14,0.94);backdrop-filter:blur(16px);
  display:none;align-items:center;justify-content:center;z-index:999;
}
.login-box{
  background:#0c1426;border:1px solid var(--border-hi);border-radius:20px;padding:32px;width:380px;text-align:center;
  box-shadow:0 24px 60px rgba(0,0,0,0.88);
}
.toast{
  position:fixed;bottom:22px;right:22px;background:#10b981;color:#04130d;padding:11px 20px;
  border-radius:12px;font-weight:800;font-size:13px;display:none;z-index:1000;box-shadow:0 10px 28px rgba(0,0,0,0.6);
}
</style>
</head>
<body>

<div id="loginModal">
  <div class="login-box">
    <div style="font-size:42px;margin-bottom:8px">👑</div>
    <h2 style="margin-bottom:4px;font-weight:800">QUANTCORE V5.0 SOVEREIGN</h2>
    <p style="font-size:12.5px;color:#94a3b8;margin-bottom:18px">58-Asset All-Regime Dual-ML Institutional Terminal</p>
    <input type="password" id="loginPass" placeholder="Пароль доступу термінала..." style="width:100%;margin-bottom:12px;padding:11px" onkeydown="if(event.key==='Enter')doLogin()">
    <button class="btn btn-sky" style="width:100%;justify-content:center;padding:11px" onclick="doLogin()">🔓 Увійти в термінал</button>
  </div>
</div>

<div class="wrap">
  <!-- TOP COMMAND BAR -->
  <div class="top-bar">
    <div class="brand">
      <div class="brand-logo">⚡</div>
      <div>
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:7px">
          <span id="statusDot" class="pulse on"></span>
          <span id="statusText" style="font-weight:800;font-size:14.5px">ONLINE</span>
          <span id="envBadge" class="pill pill-demo">🧪 DEMO $500</span>
          <span id="cartridgeBadge" class="pill pill-eng">V5.0 ALL-REGIME</span>
          <span id="regimeBadge" class="pill pill-chop">⚡ ALL-WEATHER</span>
          <span id="tierBadge" class="pill pill-tier">58 ПАР</span>
        </div>
        <div class="mono" style="font-size:11.5px;color:var(--muted);margin-top:5px">
          RAM: <b id="ramBadge" style="color:#10b981">-- MB</b> &nbsp;•&nbsp;
          Диск: <b id="diskBadge">-- MB</b> &nbsp;•&nbsp;
          TF: <b id="tfBadge" style="color:#e2e8f0">1h</b> &nbsp;•&nbsp;
          Свічка: <span id="candleBadge" style="color:#cbd5e1">--</span> &nbsp;•&nbsp;
          ⏱️ До свічки: <b id="nextCandleTimer" style="color:#38bdf8">--:--</b>
        </div>
      </div>
    </div>

    <div class="top-actions">
      <select id="riskSelect" onchange="changeRiskProfile()" title="Режим потужності та максимізації прибутку">
        <option value="CONSERVATIVE">🛡️ Conservative (2.0x)</option>
        <option value="OPTIMAL">⚖️ Optimal (3.0x)</option>
        <option value="AGGRESSIVE">🔥 Aggressive (3.5x)</option>
        <option value="OVERDRIVE">🚀 Overdrive MAX-PROFIT (3.5x)</option>
      </select>
      <select id="orchModeSelect" onchange="changeRiskProfile()" title="Режим оркестратора">
        <option value="PORTFOLIO_SYNERGY">🤝 Portfolio Synergy</option>
        <option value="SOLO_MAX">🎯 Solo Max</option>
      </select>
      <button class="btn btn-emerald" onclick="runPreflight()" title="Повна перевірка готовності сервера та маржі">🛡️ Pre-Flight</button>
      <button class="btn btn-violet" onclick="downloadV2Zip()" title="Завантажити ZIP телеметрію для звірки">📥 ZIP</button>
      <button class="btn btn-sky" onclick="triggerWakeup()" title="Миттєво перерахувати сигнали та оновити ордери">⚡ Перерахувати</button>
      <button class="btn" onclick="resetHistoryClean()" title="Архівувати старі неактивні дні/логи й почати чисті графіки">🧹 Очистити Графік</button>
      <button class="btn btn-amber" id="pauseBtn" onclick="togglePause()">⏸️ Пауза</button>
      <button class="btn" onclick="restartServer()">🔄 Рестарт</button>
      <button class="btn btn-rose" onclick="panicCloseAll()">🚨 PANIC</button>
    </div>
  </div>

  <!-- ROW 1: 8 EXECUTIVE KPI CARDS -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-title">Сумарний Equity</div>
      <div class="kpi-val" id="kpiEquity">$500.00</div>
      <div class="kpi-sub" id="kpiPnlPct">+0.00%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Чиста Альфа vs BTC</div>
      <div class="kpi-val" id="kpiAlpha">+0.00%</div>
      <div class="kpi-sub" id="kpiBtcBh">BTC B&H: +0.00%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Gross / Net Плече</div>
      <div class="kpi-val" id="kpiLev">0.00x</div>
      <div class="kpi-sub" id="kpiSleeves">4 Engines Ready</div>
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
      <div class="kpi-title">Maker Fill (Stoikov OBI)</div>
      <div class="kpi-val" id="kpiMaker" style="color:var(--sky)">0.0%</div>
      <div class="kpi-sub" id="kpiV2Orders">Ордерів: 0 / 0</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Сліпедж vs Arrival</div>
      <div class="kpi-val" id="kpiSlip">0.00 bps</div>
      <div class="kpi-sub" id="kpiSpread">Spread: 0.00 bps</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Живий Фандінг</div>
      <div class="kpi-val" id="kpiFunding">$0.000</div>
      <div class="kpi-sub" id="kpiRebals">Ребалансів: 0</div>
    </div>
  </div>

  <!-- ROW 1.5: 4-ENGINE V5.0 ALL-REGIME POWER STRIP -->
  <div class="eng-strip">
    <div class="eng-box">
      <div class="eng-top"><span style="color:#38bdf8">🧠 Engine B • 37F GPU/CPU ML Core</span><span class="mono" id="engBVal">0.00x</span></div>
      <div class="eng-meter"><div class="eng-fill" id="engBBar" style="width:0%;background:linear-gradient(90deg,#0284c7,#38bdf8)"></div></div>
      <span class="mono" style="font-size:10.5px;color:var(--muted)">Крос-секційна дисперсія: <b id="dispBadge" style="color:#e2e8f0">--</b></span>
    </div>
    <div class="eng-box">
      <div class="eng-top"><span style="color:#c4b5fd">⚡ Engine C • 24h-ML Swing + MFE TP</span><span class="mono" id="engCVal">0.00x</span></div>
      <div class="eng-meter"><div class="eng-fill" id="engCBar" style="width:0%;background:linear-gradient(90deg,#7c3aed,#c084fc)"></div></div>
      <span class="mono" style="font-size:10.5px;color:var(--muted)">4h Пробої + Фіксація +2.6 ATR + Chandelier</span>
    </div>
    <div class="eng-box">
      <div class="eng-top"><span style="color:#34d399">💎 Engine D • Carry & Margin Recycler</span><span class="mono" id="engDVal">0.00x</span></div>
      <div class="eng-meter"><div class="eng-fill" id="engDBar" style="width:0%;background:linear-gradient(90deg,#059669,#34d399)"></div></div>
      <span class="mono" style="font-size:10.5px;color:var(--muted)">Збір фандінгу + переробка вільної маржі</span>
    </div>
    <div class="eng-box">
      <div class="eng-top"><span style="color:#fbbf24">👑 Engine A • Bull / Coiled / Bear Macro</span><span class="mono" id="engAVal">0.00x</span></div>
      <div class="eng-meter"><div class="eng-fill" id="engABar" style="width:0%;background:linear-gradient(90deg,#d97706,#fbbf24)"></div></div>
      <span class="mono" style="font-size:10.5px;color:var(--muted)">Макро-тренд мейджорів та шорт обвалів</span>
    </div>
  </div>

  <!-- ROW 2: GAP-FREE CHARTS + WORKING DIVERGING ALLOCATION VECTOR -->
  <div class="split-2">
    <div class="bento-card">
      <div class="card-hdr">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="card-title">📈 Крива Капіталу (Активні Свічки Без Пустих Днів)</span>
          <button class="tab-btn active" id="tabEqMode" onclick="switchChartMode('equity')">Equity vs BTC</button>
          <button class="tab-btn" id="tabArenaMode" onclick="switchChartMode('arena')">🏆 Динаміка 6 Моделей</button>
        </div>
        <div style="display:flex;gap:5px">
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="loadCharts(1)">24г</button>
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="loadCharts(7)">7д</button>
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="loadCharts(30)">30д</button>
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="loadCharts(365)">Увесь</button>
        </div>
      </div>
      <div id="equityChart" style="width:100%;height:405px"></div>
    </div>

    <div class="bento-card" style="display:flex;flex-direction:column;justify-content:space-between">
      <div>
        <div class="card-hdr">
          <span class="card-title">🧬 Вектор Алокації V5.0 (Ціль Моделі vs Біржа)</span>
          <span class="mono" style="font-size:11px;color:var(--muted)" id="activeCountBadge">L: +0.00x | S: -0.00x</span>
        </div>
        <div id="allocChart" style="width:100%;height:260px"></div>
      </div>

      <!-- NEWS & SYSTEMIC RISK SHIELD -->
      <div style="border-top:1px solid rgba(255,255,255,0.08);padding-top:11px;margin-top:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;flex-wrap:wrap;gap:6px">
          <span style="font-size:12px;font-weight:800;color:var(--emerald)">📰 Multi-RSS + Gemini AI & Захист R5 Geo-Shock</span>
          <div style="display:flex;align-items:center;gap:6px">
            <span class="mono" style="font-size:11px;color:var(--muted)">Sent: <b id="newsVal" style="color:var(--sky)">0.00</b> | Shock: <b id="shockProbVal">0%</b></span>
            <span id="geoShockBadge" style="display:none;padding:2px 7px;border-radius:4px;background:#ef4444;color:#fff;font-size:10px;font-weight:800">🚨 R5 SHOCK</span>
            <button class="btn" style="padding:3px 8px;font-size:11px" onclick="refreshNews()">🔄 RSS</button>
          </div>
        </div>
        <ul class="news-list" id="newsList">
          <li class="news-item" style="color:var(--muted)">Очікування заголовків криптоновин...</li>
        </ul>
      </div>
    </div>
  </div>

  <!-- ROW 2.5: SHADOW ARENA LIVE 6-MODEL LEADERBOARD -->
  <div class="bento-card">
    <div class="card-hdr">
      <span class="card-title">🏆 Shadow Arena — Живий Чемпіонат 6 Сучасних Профілів V5.0 ($500 / $2,000 / $10,000 / Overdrive / FastSwing)</span>
      <span class="mono" style="font-size:11.5px;color:var(--emerald)" id="vCapBadge">Demo Cap: $500</span>
    </div>
    <div class="tbl-wrap" style="max-height:230px">
      <table>
        <thead>
          <tr><th>Ранг</th><th>Модель / Профіль</th><th>Старт $</th><th>Поточний Equity</th><th>Дохідність %</th><th>MaxDD %</th><th>Gross / Net</th><th>Позицій</th><th>Угод / Комісії</th></tr>
        </thead>
        <tbody id="arenaBody"></tbody>
      </table>
    </div>
  </div>

  <!-- ROW 3: 58-ASSET MULTI-ENGINE CONTROL MATRIX -->
  <div class="bento-card">
    <div class="card-hdr">
      <div>
        <span class="card-title" id="matrixTitle">🎛️ Матриця Універсуму та 49-Факторний Радар (58 USD-M Пар)</span>
        <div class="mono" style="font-size:11.5px;color:var(--muted);margin-top:3px">
          Breadth (&gt;EMA100): <b id="breadthVal" style="color:#fff">0.0%</b> &nbsp;|&nbsp;
          BTC vs EMA200: <b id="btcTrendVal" style="color:#fff">+0.00%</b> &nbsp;|&nbsp;
          Топ-Флагман: <b id="kpiLeader" style="color:var(--emerald)">BTCUSDT</b>
        </div>
      </div>
      <div class="filter-bar">
        <input type="text" id="coinSearch" placeholder="🔍 Пошук монети..." style="width:150px;padding:5px 9px" oninput="renderCoinsMatrix()">
        <button class="tab-btn active" id="flt-all" onclick="setCoinFilter('all')">Усі</button>
        <button class="tab-btn" id="flt-active" onclick="setCoinFilter('active')">У Книзі</button>
        <button class="tab-btn" id="flt-long" onclick="setCoinFilter('long')">Longs</button>
        <button class="tab-btn" id="flt-short" onclick="setCoinFilter('short')">Shorts</button>
        <button class="tab-btn" id="flt-majors" onclick="setCoinFilter('majors')">Majors</button>
      </div>
    </div>
    <div class="coins-grid" id="coinsGrid"></div>
  </div>

  <!-- ROW 4: EXECUTION QUALITY + TRADES + OTA & LOGS -->
  <div class="split-3">
    <div class="bento-card">
      <div class="card-hdr">
        <span class="card-title">🎯 Якість Виконання Ордерів (Stoikov OBI)</span>
        <button class="btn" style="padding:4px 9px;font-size:11px" onclick="loadV2Telemetry()">🔄</button>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr><th>Час</th><th>Пара</th><th>Двигун</th><th>Тип</th><th>Slip bps</th><th>Spread</th><th>Статус</th></tr>
          </thead>
          <tbody id="v2ExecBody"></tbody>
        </table>
      </div>
    </div>

    <div class="bento-card">
      <div class="card-hdr">
        <span class="card-title">📜 Журнал Угод Біржі</span>
        <select id="tradeSymFilter" onchange="loadTrades()" style="padding:4px 8px;font-size:11.5px">
          <option value="">Усі валюти</option>
        </select>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr><th>Час</th><th>Пара</th><th>Дія</th><th>Ціна</th><th>Net PnL</th></tr>
          </thead>
          <tbody id="tradesBody"></tbody>
        </table>
      </div>
    </div>

    <div class="bento-card" style="display:flex;flex-direction:column;justify-content:space-between">
      <div>
        <div class="card-hdr">
          <span class="card-title">🔬 Живий Лог Сервера</span>
          <button class="btn" style="padding:4px 9px;font-size:11px" onclick="loadLogs()">🔄</button>
        </div>
        <div class="log-box" id="logBox">Завантаження логів...</div>
      </div>

      <div style="border-top:1px solid rgba(255,255,255,0.08);padding-top:10px;margin-top:10px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:12px;font-weight:700;color:var(--sky)">📦 OTA Hot-Swap Моделі (.joblib)</span>
          <button class="btn" style="padding:3px 8px;font-size:11px" onclick="rollbackCartridge()">⏪ Відкат</button>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <input type="file" id="joblibFile" accept=".joblib" style="font-size:11px;color:#94a3b8;flex:1">
          <button class="btn btn-emerald" style="padding:6px 10px;font-size:11px" onclick="uploadCartridge()">🚀 Залити</button>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast">Виконано!</div>

<script>
const MAJORS_SET = new Set(['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']);
let currentChartDays = 30;
let chartViewMode = 'equity';
let lastChartPayload = null;
let isPausedState = false;
let cachedCoins = [];
let coinFilter = 'all';

// Живий секундний таймер до закриття поточної 1h свічки
function tickCandleCountdown(){
  const now = new Date();
  const remSec = 3600 - (now.getUTCMinutes() * 60 + now.getUTCSeconds()) + 4;
  const mm = String(Math.floor(remSec / 60)).padStart(2, '0');
  const ss = String(remSec % 60).padStart(2, '0');
  const el = document.getElementById('nextCandleTimer');
  if(el) el.innerText = `${mm}:${ss}`;
}
setInterval(tickCandleCountdown, 1000);
tickCandleCountdown();

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

function switchChartMode(m){
  chartViewMode = m;
  document.getElementById('tabEqMode').className = 'tab-btn' + (m === 'equity' ? ' active' : '');
  document.getElementById('tabArenaMode').className = 'tab-btn' + (m === 'arena' ? ' active' : '');
  renderMainChart();
}

function setCoinFilter(flt){
  coinFilter = flt;
  ['all','active','long','short','majors'].forEach(k => {
    const el = document.getElementById('flt-' + k);
    if(el) el.className = 'tab-btn' + (k === flt ? ' active' : '');
  });
  renderCoinsMatrix();
}

function renderCoinsMatrix(coinsArg){
  if(coinsArg) cachedCoins = coinsArg;
  const grid = document.getElementById('coinsGrid');
  const q = (document.getElementById('coinSearch').value || '').trim().toUpperCase();
  grid.innerHTML = '';

  const filtered = cachedCoins.filter(c => {
    if(q && !c.symbol.includes(q)) return false;
    const tw = Number(c.target_weight || 0), rw = Number(c.realized_weight || 0);
    if(coinFilter === 'active') return Math.abs(c.current_pos_qty) > 0 || Math.abs(tw) > 0.004 || Math.abs(rw) > 0.004;
    if(coinFilter === 'long') return c.current_pos_qty > 0 || tw > 0.004;
    if(coinFilter === 'short') return c.current_pos_qty < 0 || tw < -0.004;
    if(coinFilter === 'majors') return MAJORS_SET.has(c.symbol);
    return true;
  });

  filtered.sort((a, b) => (Math.abs(b.notional_usdt) - Math.abs(a.notional_usdt)) || (Math.abs(b.target_weight) - Math.abs(a.target_weight)));

  filtered.forEach(c => {
    const hasPos = Math.abs(c.current_pos_qty) > 0;
    const posCls = hasPos ? (c.current_pos_qty > 0 ? ' pos-long' : ' pos-short') : '';
    const card = document.createElement('div');
    card.className = 'coin-card' + posCls + (!c.enabled ? ' disabled-coin' : '');

    const normScore = Math.max(4, Math.min(100, Math.round((c.alpha_score + 1.2) / 2.4 * 100)));
    const posStr = hasPos
      ? `${c.current_pos_qty > 0 ? '🟢 LONG' : '🔴 SHORT'} $${c.notional_usdt.toFixed(1)} (${Number(c.realized_weight||0)>=0?'+':''}${Number(c.realized_weight||0).toFixed(2)}x)`
      : '⚪ КЕШ';
    const pnlColor = c.unrealized_pnl >= 0 ? '#10b981' : '#ef4444';

    let slvHtml = '';
    const sb = c.sleeve_book || '';
    if(sb === 'SLEEVE_A') slvHtml = '<span class="sleeve-tag slv-A">A•MACRO</span>';
    else if(sb === 'SLEEVE_B') slvHtml = '<span class="sleeve-tag slv-B">B•ML37</span>';
    else if(sb === 'SLEEVE_C') slvHtml = '<span class="sleeve-tag slv-AB">C•MFE</span>';
    else if(sb === 'SLEEVE_D') slvHtml = '<span class="sleeve-tag slv-A">D•CARRY</span>';
    else if(sb.startsWith('NET_')) slvHtml = `<span class="sleeve-tag slv-AB">${sb.replace('NET_','')}</span>`;

    const f = c.factors || {};
    let facHtml = '';
    if(f.z_mom !== undefined){
      facHtml = `<div class="factor-row">
        <span class="f-chip">Mom:${f.z_mom>=0?'+':''}${Number(f.z_mom).toFixed(1)}</span>
        <span class="f-chip">Car:${f.z_carry>=0?'+':''}${Number(f.z_carry).toFixed(1)}</span>
        <span class="f-chip">BAB:${f.z_bab>=0?'+':''}${Number(f.z_bab).toFixed(1)}</span>
        <span class="f-chip">Flw:${f.z_flow>=0?'+':''}${Number(f.z_flow).toFixed(1)}</span>
      </div>`;
    }

    card.innerHTML = `
      <div>
        <div class="coin-top">
          <span class="coin-sym">${c.symbol} ${slvHtml}</span>
          <span class="coin-price">$${c.price ? c.price.toLocaleString(undefined,{maximumFractionDigits:4}) : '--'}</span>
        </div>
        <span class="phase-badge ph-${c.phase}">${c.phase_label}</span>
        ${facHtml}
        <div class="coin-metrics">
          <div>На біржі: <b>${posStr}</b></div>
          <div>uPnL: <b style="color:${pnlColor}">${c.unrealized_pnl >= 0 ? '+' : ''}${c.unrealized_pnl.toFixed(2)}$</b> &nbsp;|&nbsp; Ціль V5: <b>${c.target_weight >= 0 ? '+' : ''}${Number(c.target_weight||0).toFixed(3)}x</b></div>
          <div>Score: <b>${c.alpha_score >= 0 ? '+' : ''}${c.alpha_score.toFixed(3)}</b> ${f.beta_btc !== undefined ? `| β: <b>${Number(f.beta_btc).toFixed(2)}</b>` : ''}</div>
        </div>
        <div class="bar-bg"><div class="bar-fill" style="width:${normScore}%"></div></div>
      </div>
      <div class="coin-controls">
        <select onchange="updateCoinMode('${c.symbol}', this.value)" style="flex:1;padding:4px 6px;font-size:11px">
          <option value="1" ${c.mode===1?'selected':''}>🟢 AUTO (L+S)</option>
          <option value="2" ${c.mode===2?'selected':''}>📈 LONG ONLY</option>
          <option value="3" ${c.mode===3?'selected':''}>📉 SHORT ONLY</option>
          <option value="4" ${c.mode===4?'selected':''}>🛡️ CORE ONLY</option>
          <option value="0" ${c.mode===0?'selected':''}>🔴 OFF</option>
        </select>
        <input type="number" step="0.05" min="0.2" max="3.5" value="${c.base_weight}"
               style="width:56px;padding:4px 6px;font-size:11px" title="Вага пріоритету"
               onchange="updateCoinWeight('${c.symbol}', this.value)">
      </div>
    `;
    grid.appendChild(card);
  });
}

function renderAllocationVector(coins){
  const active = (coins || []).filter(c => Math.abs(Number(c.target_weight || 0)) > 0.003 || Math.abs(Number(c.realized_weight || 0)) > 0.003);
  active.sort((a, b) => (Number(b.target_weight || b.realized_weight || 0)) - (Number(a.target_weight || a.realized_weight || 0)));

  const longSum = active.reduce((acc, c) => acc + Math.max(0, Number(c.target_weight || 0)), 0);
  const shortSum = active.reduce((acc, c) => acc + Math.min(0, Number(c.target_weight || 0)), 0);
  const actPos = (coins || []).filter(c => Math.abs(c.current_pos_qty) > 0).length;
  document.getElementById('activeCountBadge').innerHTML =
    `<span style="color:#10b981">L:+${longSum.toFixed(2)}x</span> | <span style="color:#ef4444">S:${shortSum.toFixed(2)}x</span> | Поз:${actPos}`;

  if(!active.length){
    Plotly.react('allocChart', [], {
      paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(6,10,20,0.65)',
      annotations:[{text:'Книга в 100% USDT кеші — натисніть ⚡ Перерахувати', showarrow:false, font:{color:'#64748b', size:12, family:'JetBrains Mono'}}],
      xaxis:{visible:false}, yaxis:{visible:false}, margin:{l:10,r:10,t:10,b:10}
    }, {displayModeBar:false, responsive:true});
    return;
  }

  const syms = active.map(c => c.symbol.replace('USDT',''));
  const tgtW = active.map(c => Number(c.target_weight || 0));
  const realW = active.map(c => Number(c.realized_weight || 0));
  const tgtColors = tgtW.map(w => w >= 0 ? 'rgba(16,185,129,0.88)' : 'rgba(239,68,68,0.88)');
  const hoverTxt = active.map(c => `${c.symbol} [${c.sleeve_book||'CORE'}]<br>На біржі: $${Number(c.notional_usdt||0).toFixed(1)}`);

  Plotly.react('allocChart', [
    {
      x: syms, y: tgtW, name: 'Ціль V5.0 (x)', type: 'bar',
      marker: {color: tgtColors, line:{width:0}},
      text: hoverTxt, hovertemplate: '%{text}<br>Ціль: %{y:+.3f}x<extra></extra>'
    },
    {
      x: syms, y: realW, name: 'Факт на Біржі (x)', type: 'scatter', mode: 'markers',
      marker: {color: '#38bdf8', size: 7, symbol: 'diamond', line:{color:'#03060e', width:1.2}},
      hovertemplate: '%{x}: Факт %{y:+.3f}x<extra></extra>'
    }
  ], {
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(6,10,20,0.68)',
    font:{color:'#cbd5e1', family:'JetBrains Mono', size:10},
    margin:{l:40,r:10,t:24,b:38},
    legend:{orientation:'h', y:1.15, x:0, font:{size:10}},
    xaxis:{gridcolor:'#131d31', tickangle:-28},
    yaxis:{gridcolor:'#131d31', zerolinecolor:'#475569', zerolinewidth:1.4, title:''}
  }, {displayModeBar:false, responsive:true});
}

function renderMainChart(){
  if(!lastChartPayload) return;
  const ch = lastChartPayload.chart || {};
  if(chartViewMode === 'arena'){
    const aMap = ch.arena_series || {};
    const palette = ['#10b981','#38bdf8','#c084fc','#f59e0b','#f43f5e','#94a3b8'];
    const traces = Object.keys(aMap).map((bid, idx) => ({
      x: aMap[bid].times, y: aMap[bid].ret_pct, name: bid,
      type: 'scatter', mode: aMap[bid].times.length < 3 ? 'lines+markers' : 'lines',
      line: {width: idx === 0 ? 2.6 : 1.7, color: palette[idx % palette.length]}
    }));
    Plotly.react('equityChart', traces, {
      paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(6,10,20,0.68)',
      font:{color:'#cbd5e1', family:'JetBrains Mono', size:10.5},
      margin:{l:44,r:14,t:26,b:34}, hovermode:'x unified',
      legend:{orientation:'h', y:1.13, font:{size:10}},
      xaxis:{type:'category', gridcolor:'#131d31', nticks:8},
      yaxis:{gridcolor:'#131d31', zerolinecolor:'#475569', title:'Дохідність %'}
    }, {displayModeBar:false, responsive:true});
    return;
  }

  if(!ch.times || !ch.times.length) return;
  const pointMode = ch.times.length < 3 ? 'lines+markers' : 'lines';
  Plotly.react('equityChart', [
    {
      x: ch.times, y: ch.equity_ret_pct, name:'QuantCore V5.0 (%)',
      type:'scatter', mode: pointMode,
      fill:'tozeroy', fillcolor:'rgba(16,185,129,0.09)',
      line:{color:'#10b981', width:2.6}, marker:{size:7, color:'#10b981'}, yaxis:'y1'
    },
    {
      x: ch.times, y: ch.btc_ret_pct, name:'Buy & Hold BTC (%)',
      type:'scatter', mode: pointMode,
      line:{color:'#f59e0b', width:1.5, dash:'dot'}, marker:{size:5, color:'#f59e0b'}, yaxis:'y1'
    },
    {
      x: ch.times, y: ch.drawdown_pct, name:'Drawdown (%)',
      type:'scatter', mode:'lines', fill:'tozeroy',
      fillcolor:'rgba(239,68,68,0.18)', line:{color:'#ef4444', width:1.2}, yaxis:'y2'
    }
  ], {
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(6,10,20,0.68)',
    font:{color:'#cbd5e1', family:'JetBrains Mono', size:10.5},
    margin:{l:46,r:14,t:24,b:32}, hovermode:'x unified',
    legend:{orientation:'h', y:1.12},
    xaxis:{type:'category', gridcolor:'#131d31', nticks:8},
    yaxis:{domain:[0.31, 1.0], gridcolor:'#131d31', zerolinecolor:'#334155', title:'Return %'},
    yaxis2:{domain:[0.0, 0.24], gridcolor:'#131d31', title:'DD %'}
  }, {displayModeBar:false, responsive:true});
}

async function resetHistoryClean(){
  if(!confirm('🧹 Архівувати старі неактивні дні/логи в backups/ та почати ідеально чистий графік з поточного балансу?')) return;
  try{
    const r = await apiFetch('/api/v1/control/reset-history', {method:'POST'});
    if(r && r.ok){
      showToast('✨ Старі логи архівовано! Новий чистий графік запущено.');
      setTimeout(refreshAll, 2000);
    }
  }catch(e){ showToast('❌ Помилка очищення', true); }
}

async function updateCoinMode(sym, modeVal){
  const m = parseInt(modeVal);
  await apiFetch('/api/v1/control/coin', {
    method:'POST', body: JSON.stringify({symbol: sym, mode: m, enabled: m !== 0})
  });
  showToast(`🎛️ ${sym}: режим оновлено!`);
  loadState();
}

async function updateCoinWeight(sym, wVal){
  await apiFetch('/api/v1/control/coin', {
    method:'POST', body: JSON.stringify({symbol: sym, base_weight: parseFloat(wVal)})
  });
  showToast(`⚖️ ${sym}: вагу змінено на ${wVal}x`);
  loadState();
}

async function changeRiskProfile(){
  const prof = document.getElementById('riskSelect').value;
  const om = document.getElementById('orchModeSelect').value;
  try{
    const r = await apiFetch('/api/v1/control/risk', {
      method:'POST', body: JSON.stringify({risk_profile: prof, orchestrator_mode: om})
    });
    if(r && r.ok) showToast(`🚀 Активовано профіль: ${prof}!`);
    else showToast(`❌ ${r?.detail || 'Помилка'}`, true);
  }catch(e){ showToast(`❌ ${e.message}`, true); }
  setTimeout(refreshAll, 2000);
}

async function runPreflight(){
  try{
    const d = await apiFetch('/api/v1/system/preflight');
    if(!d.ok || !d.preflight){ showToast('⚠️ Pre-Flight недоступний', true); return; }
    const p = d.preflight;
    alert(
      `🛡️ QUANTCORE V5.0 ALL-REGIME PRE-FLIGHT\n` +
      `─────────────────────────────────────\n` +
      `• Режим: ${p.demo_trading_mode ? '🧪 DEMO/TESTNET' : '🔴 LIVE REAL'}\n` +
      `• Віртуальний депозит: ${p.virtual_equity_cap > 0 ? '$'+p.virtual_equity_cap : '100% гаманця'}\n` +
      `• Ядро: ${String(p.cartridge_engine).toUpperCase()} (${p.symbols_count} пар, ${p.candle_timeframe})\n` +
      `• Зв'язок Binance / One-Way: ${p.exchange_reachable ? '✅ OK' : 'NO KEYS'} / ${p.one_way_mode_ok ? '✅ OK' : 'WARN'}\n` +
      `• 37-Feature Dual-ML V5: ${p.ml_ranker_v5_present ? '✅ Завантажено' : (p.ml_ranker_v3_present ? '✅ V4 Fallback' : 'Лінійний')}\n` +
      `• Гаманець USDT: $${p.usdt_wallet_balance} | BNB: ${p.bnb_fee_burn_balance} | BFUSD: $${p.bfusd_collateral_balance}\n` +
      `• RAM процесу: ${p.ram_rss_mb} MB`
    );
  }catch(e){ showToast('❌ Помилка Pre-Flight', true); }
}

function renderArena(rows){
  const tb = document.getElementById('arenaBody');
  if(!tb) return;
  tb.innerHTML = '';
  if(!rows || !rows.length){
    tb.innerHTML = '<tr><td colspan="9" style="color:#64748b;text-align:center">Shadow Arena ініціалізована — очікування першої свічки...</td></tr>';
    return;
  }
  const medals = {1:'🥇 1', 2:'🥈 2', 3:'🥉 3'};
  rows.forEach(r => {
    const tr = document.createElement('tr');
    const rc = r.return_pct >= 0 ? '#10b981' : '#ef4444';
    tr.innerHTML = `
      <td><b>${medals[r.rank] || '#'+r.rank}</b></td>
      <td><b style="color:#7dd3fc">${r.bot_id}</b> <span style="color:#94a3b8;font-size:11px">${r.label}</span></td>
      <td>$${r.initial_equity.toLocaleString()}</td>
      <td><b>$${r.equity.toLocaleString(undefined,{minimumFractionDigits:2})}</b></td>
      <td style="color:${rc};font-weight:800">${r.return_pct>=0?'+':''}${r.return_pct.toFixed(2)}%</td>
      <td style="color:#fca5a5">${r.max_dd_pct.toFixed(2)}%</td>
      <td>${r.gross_lev.toFixed(2)}x / ${r.net_lev>=0?'+':''}${r.net_lev.toFixed(2)}x</td>
      <td>${r.active_positions}</td>
      <td>${r.trades_count} ($${r.fees_usd.toFixed(2)})</td>
    `;
    tb.appendChild(tr);
  });
}

async function downloadV2Zip(){
  const tok = localStorage.getItem('qc_token') || '';
  showToast('📦 Формування ZIP-архіву телеметрії...');
  try{
    const resp = await fetch('/api/v1/v2/export', {headers:{'X-Api-Key': tok}});
    if(!resp.ok){ showToast('❌ Не вдалося створити ZIP', true); return; }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'quantcore_v5_telemetry.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('✅ ZIP-архів завантажено!');
  }catch(e){ showToast('❌ Помилка завантаження', true); }
}

async function refreshNews(){
  showToast('📰 Оновлення RSS-стрічок та ШІ-оцінки...');
  try{
    const d = await apiFetch('/api/v1/news?refresh=true');
    if(d.ok && d.news) renderNews(d.news);
    showToast('✅ Новини оновлено!');
  }catch(e){}
}

function renderNews(news){
  if(!news) return;
  const s = Number(news.macro_sentiment || 0);
  const p = Number(news.geo_shock_prob || 0);
  document.getElementById('newsVal').innerText = (s>=0?'+':'') + s.toFixed(2);
  document.getElementById('newsVal').style.color = s > 0.1 ? '#10b981' : (s < -0.1 ? '#ef4444' : '#38bdf8');
  document.getElementById('shockProbVal').innerText = Math.round(p * 100) + '%';
  document.getElementById('geoShockBadge').style.display = news.is_geo_shock ? 'inline-block' : 'none';

  const ul = document.getElementById('newsList');
  const hl = news.headlines || [];
  if(hl.length > 0){
    ul.innerHTML = hl.slice(0, 6).map(h => `<li class="news-item">${h.replace(/</g,'&lt;')}</li>`).join('');
  }
}

async function triggerWakeup(){
  await apiFetch('/api/v1/control/wakeup', {method:'POST'});
  showToast('⚡ Примусовий перерахунок 58 пар запущено!');
  setTimeout(refreshAll, 3000);
}

async function togglePause(){
  await apiFetch('/api/v1/control/pause', {
    method:'POST', body: JSON.stringify({paused: !isPausedState})
  });
  showToast(!isPausedState ? '⏸️ Торгівлю призупинено' : '▶️ Торгівлю відновлено!');
  loadState();
}

async function restartServer(){
  if(!confirm('Перезавантажити сервер QuantCore зараз? Служба systemd підніме його за 3 секунди.')) return;
  try{
    await apiFetch('/api/v1/control/restart', {method:'POST'});
    showToast('🔄 Перезавантаження (3 сек)...');
    setTimeout(refreshAll, 5000);
  }catch(e){}
}

async function panicCloseAll(){
  if(!confirm('🚨 ЕКСТРЕНО ЗАКРИТИ ВСІ ВІДКРИТІ ПОЗИЦІЇ У 100% USDT КЕШ?')) return;
  await apiFetch('/api/v1/control/panic', {method:'POST'});
  showToast('🚨 Усі позиції ліквідовано в USDT!', true);
  refreshAll();
}

async function uploadCartridge(){
  const fInput = document.getElementById('joblibFile');
  if(!fInput.files.length){ showToast('Оберіть файл .joblib', true); return; }
  const fd = new FormData();
  fd.append('file', fInput.files[0]);
  showToast('⏳ Hot-Swap моделі...');
  const tok = localStorage.getItem('qc_token') || '';
  const resp = await fetch('/api/v1/cartridge/upload', {
    method:'POST', headers:{'X-Api-Key': tok}, body: fd
  });
  const d = await resp.json();
  if(resp.ok && d.ok){
    showToast(`🚀 Hot-Swap: ${d.active_cartridge}`);
    fInput.value = '';
    refreshAll();
  } else {
    showToast(`❌ ${d.detail || 'Invalid file'}`, true);
  }
}

async function rollbackCartridge(){
  if(!confirm('Повернути попередній картридж моделі (.joblib)?')) return;
  const r = await apiFetch('/api/v1/cartridge/rollback', {method:'POST'});
  if(r.ok){ showToast(`⏪ Відкат: ${r.active_cartridge}`); refreshAll(); }
}

async function loadState(){
  try{
    const d = await apiFetch('/api/v1/state');
    if(!d.ok) return;
    const eng = d.engine || {};
    const res = d.resources || {};
    const t = eng.telemetry || {};
    const v2 = d.v2_analytics || {};

    isPausedState = Boolean(eng.is_paused);
    document.getElementById('statusDot').className = 'pulse ' + (isPausedState ? 'warn' : 'on');
    document.getElementById('statusText').innerText = isPausedState ? 'PAUSED' : 'ONLINE (Zero-Idle)';
    document.getElementById('pauseBtn').innerText = isPausedState ? '▶️ Старт' : '⏸️ Пауза';

    const vCap = Number(d.virtual_equity_cap || 0);
    const envEl = document.getElementById('envBadge');
    envEl.className = 'pill ' + (d.demo_trading ? 'pill-demo' : 'pill-live');
    envEl.innerText = d.demo_trading ? (vCap > 0 ? `🧪 DEMO $${vCap.toFixed(0)}` : '🧪 DEMO') : '🔴 LIVE REAL';

    document.getElementById('cartridgeBadge').innerText = String(d.cartridge_engine || 'v5').toUpperCase() + ' SOVEREIGN';
    document.getElementById('tfBadge').innerText = d.candle_timeframe || '1h';
    document.getElementById('ramBadge').innerText = (res.ram_rss_mb || '--') + ' MB';
    document.getElementById('diskBadge').innerText = (res.storage_used_mb || '--') + ' MB';
    document.getElementById('candleBadge').innerText = String(t.timestamp || eng.last_candle_ts || '--').slice(5,16);

    if(eng.risk_profile) document.getElementById('riskSelect').value = eng.risk_profile;
    if(eng.orchestrator_mode) document.getElementById('orchModeSelect').value = eng.orchestrator_mode;

    if(t.total_equity !== undefined && Number(t.total_equity) > 0){
      document.getElementById('kpiEquity').innerText = '$' + Number(t.total_equity).toLocaleString(undefined,{minimumFractionDigits:2});
    }

    const ag = Number(t.a_gross||0), bg = Number(t.b_gross||0), cg = Number(t.c_gross||0), dg = Number(t.d_gross||0);
    const grossL = Number(t.gross_leverage || (ag + bg + cg + dg) || 0);
    const netL = Number(t.net_leverage || 0);
    document.getElementById('kpiLev').innerText = `${grossL.toFixed(2)}x / ${netL>=0?'+':''}${netL.toFixed(2)}x`;
    document.getElementById('kpiSleeves').innerText = `B:${bg.toFixed(2)} C:${cg.toFixed(2)} D:${dg.toFixed(2)} A:${ag.toFixed(2)}`;
    document.getElementById('kpiLeader').innerText = t.top_leader || 'BTCUSDT';

    // 4-Engine Power Strip
    document.getElementById('engBVal').innerText = bg.toFixed(2) + 'x';
    document.getElementById('engBBar').style.width = Math.min(100, bg / 2.2 * 100).toFixed(0) + '%';
    document.getElementById('engCVal').innerText = cg.toFixed(2) + 'x';
    document.getElementById('engCBar').style.width = Math.min(100, cg / 0.65 * 100).toFixed(0) + '%';
    document.getElementById('engDVal').innerText = dg.toFixed(2) + 'x';
    document.getElementById('engDBar').style.width = Math.min(100, dg / 0.55 * 100).toFixed(0) + '%';
    document.getElementById('engAVal').innerText = ag.toFixed(2) + 'x';
    document.getElementById('engABar').style.width = Math.min(100, ag / 0.55 * 100).toFixed(0) + '%';
    document.getElementById('dispBadge').innerText = Number(t.cs_dispersion || 0).toFixed(3);

    const vcEl = document.getElementById('vCapBadge');
    if(vcEl) vcEl.innerText = vCap > 0 ? `🎯 Активна репетиція старту: $${vCap.toFixed(0)} USDT (OVERDRIVE MAX-PROFIT)` : 'Баланс: 100% гаманця';
    if(d.shadow_arena) renderArena(d.shadow_arena);

    const brPct = Number(t.market_breadth || 0) * 100;
    const btPct = Number(t.btc_trend || 0) * 100;
    document.getElementById('breadthVal').innerText = brPct.toFixed(1) + '%';
    document.getElementById('btcTrendVal').innerText = (btPct>=0?'+':'') + btPct.toFixed(2) + '%';
    document.getElementById('btcTrendVal').style.color = btPct >= 0 ? '#10b981' : '#ef4444';

    const regEl = document.getElementById('regimeBadge');
    if(btPct > 2.0 && brPct >= 52){
      regEl.className = 'pill pill-bull'; regEl.innerText = '🐂 BULL TREND';
    } else if(btPct < -2.5 && brPct <= 35){
      regEl.className = 'pill pill-bear'; regEl.innerText = '🐻 BEAR SHIELD';
    } else {
      regEl.className = 'pill pill-chop'; regEl.innerText = '⚡ CHOP / MFE HARVEST';
    }

    if(v2 && v2.ok){
      document.getElementById('kpiMaker').innerText = Number(v2.maker_fill_pct || 0).toFixed(1) + '%';
      document.getElementById('kpiV2Orders').innerText = `Ордерів: ${v2.orders_filled || 0} / ${v2.orders_total || 0}`;
      const slp = Number(v2.avg_slippage_arrival_bps || 0);
      document.getElementById('kpiSlip').innerText = (slp>=0?'+':'') + slp.toFixed(2) + ' bps';
      document.getElementById('kpiSlip').style.color = slp <= 2.5 ? '#10b981' : '#f59e0b';
      document.getElementById('kpiSpread').innerText = `Spread: ${Number(v2.avg_spread_bps||0).toFixed(2)} bps`;
      const fnd = Number(v2.net_funding_income_usdt || 0);
      document.getElementById('kpiFunding').innerText = (fnd>=0?'+$':'-$') + Math.abs(fnd).toFixed(3);
      document.getElementById('kpiFunding').style.color = fnd >= 0 ? '#10b981' : '#f59e0b';
      document.getElementById('kpiRebals').innerText = `Ребалансів: ${v2.rebalances_logged || 0}`;
    }

    if(d.news) renderNews(d.news);

    const coins = eng.coins || [];
    document.getElementById('tierBadge').innerText = `${coins.length} ПАР`;
    document.getElementById('matrixTitle').innerText = `🎛️ Матриця Універсуму та 49-Факторний Радар (${coins.length} USD-M Пар)`;

    const filterEl = document.getElementById('tradeSymFilter');
    if (filterEl && coins.length > 0) {
      const curVal = filterEl.value;
      const coinSyms = coins.map(c => c.symbol).filter(Boolean);
      const existingOpts = Array.from(filterEl.options).map(o => o.value);
      if (coinSyms.some(s => !existingOpts.includes(s)) || existingOpts.length <= 1) {
        filterEl.innerHTML = '<option value="">Усі валюти</option>' + coinSyms.map(s => `<option value="${s}">${s}</option>`).join('');
        filterEl.value = curVal;
      }
    }

    renderCoinsMatrix(coins);
    renderAllocationVector(coins);
  }catch(e){}
}

async function loadCharts(days){
  if(days) currentChartDays = days;
  try{
    const d = await apiFetch('/api/v1/equity?days=' + currentChartDays);
    if(!d.ok || !d.kpis) return;
    lastChartPayload = d;
    const k = d.kpis;

    if(k.latest_equity !== undefined){
      document.getElementById('kpiEquity').innerText = '$' + k.latest_equity.toLocaleString(undefined,{minimumFractionDigits:2});
      document.getElementById('kpiPnlPct').innerText = `${k.total_pnl_pct>=0?'+':''}${k.total_pnl_pct.toFixed(2)}% (WR: ${k.win_rate_pct.toFixed(0)}%)`;
      document.getElementById('kpiPnlPct').style.color = k.total_pnl_pct>=0 ? '#10b981' : '#ef4444';
      document.getElementById('kpiAlpha').innerText = (k.alpha_vs_btc_pct>=0?'+':'') + k.alpha_vs_btc_pct.toFixed(2) + '%';
      document.getElementById('kpiAlpha').style.color = k.alpha_vs_btc_pct>=0 ? '#10b981' : '#f59e0b';
      document.getElementById('kpiBtcBh').innerText = 'BTC B&H: ' + (k.btc_bh_pct>=0?'+':'') + k.btc_bh_pct.toFixed(2) + '%';
      document.getElementById('kpiSharpe').innerText = k.sharpe_ratio.toFixed(2);
      document.getElementById('kpiCalmar').innerText = 'Calmar: ' + k.calmar_ratio.toFixed(2);
      document.getElementById('kpiMdd').innerText = k.max_drawdown_pct.toFixed(2) + '%';
      document.getElementById('kpiFees').innerText = `Fee: $${k.total_fees_usdt.toFixed(2)} | Оп: ${k.total_ops}`;
    }
    renderMainChart();
  }catch(e){}
}

async function loadV2Telemetry(){
  try{
    const d = await apiFetch('/api/v1/v2/telemetry?limit=25');
    if(!d.ok) return;
    const tb = document.getElementById('v2ExecBody');
    tb.innerHTML = '';
    const rows = d.executions || [];
    if(!rows.length){
      tb.innerHTML = '<tr><td colspan="7" style="color:#64748b;text-align:center">Очікування нових ордерів чистої епохи V5.0...</td></tr>';
      return;
    }
    rows.forEach(r => {
      const tr = document.createElement('tr');
      const sCol = r.side === 'BUY' ? '#10b981' : '#ef4444';
      const mkLbl = r.is_maker ? '<span style="color:#38bdf8">MAKER</span>' : (r.maker_fallback_used ? '<span style="color:#f59e0b">TAKER_FB</span>' : 'NONE');
      const slp = Number(r.slippage_arrival_bps || 0);
      tr.innerHTML = `
        <td>${String(r.ts || '').slice(5,16)}</td>
        <td><b>${r.symbol}</b> <span style="color:${sCol}">${r.side}</span></td>
        <td style="color:#94a3b8">${String(r.sleeve_book||'').replace('SLEEVE_','')}</td>
        <td>${mkLbl}</td>
        <td style="color:${slp<=2.5?'#10b981':'#f59e0b'}">${slp>=0?'+':''}${slp.toFixed(1)}</td>
        <td>${Number(r.spread_bps||0).toFixed(1)}</td>
        <td>${r.order_status}</td>
      `;
      tb.appendChild(tr);
    });
  }catch(e){}
}

async function loadTrades(){
  try{
    const sym = document.getElementById('tradeSymFilter').value;
    const d = await apiFetch('/api/v1/trades?limit=35&symbol=' + sym);
    const tb = document.getElementById('tradesBody');
    tb.innerHTML = '';
    (d.trades || []).forEach(t => {
      const tr = document.createElement('tr');
      const sCol = t.side === 'BUY' ? '#10b981' : '#ef4444';
      const pCol = t.net_pnl >= 0 ? '#10b981' : '#ef4444';
      tr.innerHTML = `
        <td>${String(t.time||'').slice(5,16)}</td>
        <td><b>${t.symbol}</b></td>
        <td style="color:${sCol};font-weight:700">${t.side} ${t.amount}</td>
        <td>$${t.price.toLocaleString()}</td>
        <td style="color:${pCol};font-weight:700">${t.net_pnl>=0?'+':''}$${t.net_pnl.toFixed(2)}</td>
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
  loadV2Telemetry();
  loadTrades();
  loadLogs();
}

refreshAll();
setInterval(loadState, 8000);
setInterval(loadCharts, 30000);
setInterval(loadV2Telemetry, 15000);
setInterval(loadLogs, 15000);
</script>
</body>
</html>
"""
