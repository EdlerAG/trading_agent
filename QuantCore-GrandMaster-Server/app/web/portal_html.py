PORTAL_HTML: str = r"""<!DOCTYPE html>
<html lang="uk" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QuantCore Execution &amp; Risk Terminal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" media="print" onload="this.media='all'">
<style>
:root,
[data-theme="light"]{
  --bg:#F5F7FA;
  --surface:#FFFFFF;
  --surface-2:#EEF2F6;
  --border:#CBD5E1;
  --control-border:#64748B;
  --ink:#0F172A;
  --ink-2:#334155;
  --muted:#475569;
  --accent:#0B5CAB;
  --accent-hover:#084785;
  --accent-soft:#E0EEFB;
  --long:#0F766E;
  --long-soft:#CCFBF1;
  --short:#B91C1C;
  --short-soft:#FEE2E2;
  --caution:#9A3412;
  --caution-soft:#FFEDD5;
  --chart-grid:#E2E8F0;
  --chart-zero:#64748B;
  --shadow-elev:0 2px 8px rgba(15,23,42,0.06);
  --scrim:rgba(15,23,42,0.58);
}
[data-theme="dark"]{
  --bg:#0B1017;
  --surface:#121923;
  --surface-2:#182230;
  --border:#263447;
  --control-border:#6C819D;
  --ink:#F1F5F9;
  --ink-2:#CBD5E1;
  --muted:#94A3B8;
  --accent:#60A5FA;
  --accent-hover:#93C5FD;
  --accent-soft:#172A45;
  --long:#34D399;
  --long-soft:#0D2E27;
  --short:#F87171;
  --short-soft:#35161B;
  --caution:#FBBF24;
  --caution-soft:#33240B;
  --chart-grid:#1E293B;
  --chart-zero:#6C819D;
  --shadow-elev:0 4px 14px rgba(0,0,0,0.36);
  --scrim:rgba(4,8,14,0.78);
}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;scroll-padding-top:76px}
body{
  background:var(--bg);
  color:var(--ink);
  font-family:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:clamp(13px,0.92vw,14.5px);
  line-height:1.45;
  min-height:100dvh;
  font-variant-numeric:tabular-nums;
  overflow-x:hidden;
}
.mono{
  font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,Consolas,monospace;
  font-variant-numeric:tabular-nums;
}
.sr-only{
  position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
}
.skip-link{
  position:absolute;left:-9999px;top:8px;z-index:2000;
  background:var(--accent);color:#FFFFFF;padding:10px 14px;border-radius:6px;font-weight:600;
}
.skip-link:focus{left:12px}

a[href],button:not(:disabled),summary,select:not(:disabled),input[type="checkbox"]:not(:disabled),input[type="radio"]:not(:disabled),label[for],[role="button"]:not([aria-disabled="true"]),[role="tab"]:not([aria-disabled="true"]){
  cursor:pointer;
}
button:disabled,select:disabled,input:disabled,[aria-disabled="true"]{
  cursor:not-allowed;opacity:0.55;
}
:focus-visible{
  outline:2px solid var(--accent);
  outline-offset:2px;
}

.shell{max-width:1680px;margin:0 auto;padding:12px 16px 36px}

/* Header & Navigation */
.site-header{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:8px;
  padding:12px 16px;
  margin-bottom:10px;
  box-shadow:var(--shadow-elev);
}
.hdr-top{
  display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;
}
.brand-block{display:flex;flex-direction:column;gap:4px;min-width:0}
.brand-row{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.brand-mark{
  display:inline-flex;align-items:center;justify-content:center;
  padding:3px 8px;border-radius:4px;background:var(--accent);color:#FFFFFF;
  font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:12px;letter-spacing:0.3px;
}
[data-theme="dark"] .brand-mark{background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent)}
h1{font-size:clamp(16px,1.35vw,19px);font-weight:700;color:var(--ink);letter-spacing:-0.01em}
.sys-strip{
  display:flex;flex-wrap:wrap;gap:10px;align-items:center;
  font-size:12px;color:var(--muted);
}
.sys-strip strong{color:var(--ink);font-weight:600}

.status-chip{
  display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:4px;
  font-size:11.5px;font-weight:600;border:1px solid var(--control-border);
  background:var(--surface-2);color:var(--ink);
}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--long);flex-shrink:0}
.status-chip.paused .status-dot{background:var(--caution)}
.status-chip.offline .status-dot{background:var(--short)}
.chip-long{background:var(--long-soft);color:var(--long);border-color:var(--long)}
.chip-short{background:var(--short-soft);color:var(--short);border-color:var(--short)}
.chip-caution{background:var(--caution-soft);color:var(--caution);border-color:var(--caution)}
.chip-accent{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}

.ctrl-cluster{
  display:flex;align-items:center;flex-wrap:wrap;gap:8px;
}
.field-inline{display:inline-flex;align-items:center;gap:6px}
.field-inline label{font-size:12px;color:var(--muted);font-weight:500}

button,select,input[type="number"],input[type="password"],input[type="text"]{
  font-family:inherit;
  font-size:12.5px;
  border-radius:6px;
  border:1px solid var(--control-border);
  background:var(--surface);
  color:var(--ink);
  min-height:36px;
  padding:6px 11px;
  transition:background-color 0.14s ease,border-color 0.14s ease,transform 0.08s ease;
}
button{font-weight:600;display:inline-flex;align-items:center;justify-content:center;gap:6px}
button:hover:not(:disabled),select:hover:not(:disabled){
  background:var(--surface-2);border-color:var(--ink-2);
}
button:active:not(:disabled){transform:translateY(1px)}

.btn-primary{
  background:var(--accent);color:#FFFFFF;border-color:var(--accent);
}
.btn-primary:hover:not(:disabled){
  background:var(--accent-hover);border-color:var(--accent-hover);color:#FFFFFF;
}
[data-theme="dark"] .btn-primary{color:#0B1017;background:var(--accent);border-color:var(--accent)}
[data-theme="dark"] .btn-primary:hover:not(:disabled){background:var(--accent-hover);color:#0B1017}

.btn-caution{
  background:var(--caution-soft);color:var(--caution);border-color:var(--caution);
}
.btn-caution:hover:not(:disabled){filter:brightness(0.96)}
.btn-danger{
  background:var(--short-soft);color:var(--short);border-color:var(--short);
}
.btn-danger:hover:not(:disabled){filter:brightness(0.96)}

/* Section Nav */
.sec-nav{
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;
  background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:6px 12px;margin-bottom:14px;
}
.nav-links{display:flex;flex-wrap:wrap;gap:6px;list-style:none}
.nav-links a{
  display:inline-flex;align-items:center;padding:6px 11px;border-radius:5px;
  text-decoration:none;color:var(--ink-2);font-size:12.5px;font-weight:600;
  border:1px solid transparent;min-height:36px;
}
.nav-links a:hover{background:var(--surface-2);color:var(--ink)}
.nav-links a.current{
  background:var(--accent-soft);color:var(--accent);border-color:var(--accent);
}
.nav-toggle{display:none}

/* Banner for global error / stale warning */
.alert-banner{
  display:none;align-items:center;justify-content:space-between;gap:12px;
  padding:10px 14px;border-radius:6px;margin-bottom:12px;
  background:var(--short-soft);color:var(--short);border:1px solid var(--short);
  font-size:13px;font-weight:600;
}

/* Primary Overview Split (Focal Ledger + Equity Canvas) */
.overview-layout{
  display:grid;grid-template-columns:340px minmax(0,1fr);gap:14px;margin-bottom:14px;
}
.panel{
  background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:14px 16px;min-width:0;
}
.panel-elevated{box-shadow:var(--shadow-elev)}
.panel-hdr{
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;
  margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--border);
}
.panel-hdr h2{font-size:14.5px;font-weight:700;color:var(--ink)}
.panel-sub{font-size:12px;color:var(--muted)}

.focal-equity{
  padding-bottom:12px;margin-bottom:12px;border-bottom:1px solid var(--border);
}
.focal-label{font-size:12px;color:var(--muted);font-weight:500}
.focal-value{
  font-size:clamp(26px,2.4vw,32px);font-weight:700;line-height:1.15;margin:3px 0 5px;
  color:var(--ink);
}
.focal-delta{font-size:13px;font-weight:600}
.pos-val{color:var(--long)}
.neg-val{color:var(--short)}
.warn-val{color:var(--caution)}

.ledger-dl{display:grid;grid-template-columns:1fr auto;row-gap:8px;column-gap:10px;font-size:12.5px}
.ledger-dl dt{color:var(--muted)}
.ledger-dl dd{text-align:right;font-weight:600;color:var(--ink)}

/* Chart Controls & Canvas */
.seg-group{display:inline-flex;flex-wrap:wrap;gap:4px}
.seg-btn{
  padding:5px 10px;min-height:32px;font-size:12px;border-radius:5px;
  background:var(--surface-2);border:1px solid var(--border);color:var(--ink-2);
}
.seg-btn[aria-pressed="true"],.seg-btn.active{
  background:var(--accent-soft);color:var(--accent);border-color:var(--accent);
}
.canvas-stage{
  position:relative;width:100%;height:350px;
  background:var(--surface);border-radius:6px;
}
.canvas-stage.compact{height:260px}
.canvas-stage canvas{display:block;width:100%;height:100%}
.chart-tooltip{
  display:none;position:absolute;pointer-events:none;z-index:20;
  background:var(--surface);color:var(--ink);border:1px solid var(--control-border);
  border-radius:6px;padding:7px 10px;font-size:11.5px;box-shadow:var(--shadow-elev);
  max-width:250px;line-height:1.4;
}
.state-placeholder{
  display:none;align-items:center;justify-content:center;text-align:center;
  position:absolute;inset:0;padding:18px;background:var(--surface-2);
  border-radius:6px;color:var(--muted);font-size:13px;
}

/* Pipeline Flow & Risk Armor */
.pipeline-section{margin-bottom:14px}
.pipeline-rail{
  display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-bottom:12px;
}
.pipe-step{
  background:var(--surface-2);border:1px solid var(--border);border-radius:6px;
  padding:10px 12px;min-width:0;display:flex;flex-direction:column;gap:4px;
}
.pipe-kicker{font-size:11.5px;color:var(--muted);font-weight:600}
.pipe-main{font-size:16px;font-weight:700;color:var(--ink)}
.pipe-note{font-size:11.5px;color:var(--ink-2)}

.armor-grid{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;
}
.armor-meter{
  border:1px solid var(--border);border-radius:6px;padding:10px 12px;background:var(--surface);
}
.meter-hdr{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-bottom:6px}
.meter-hdr span:first-child{color:var(--muted);font-weight:500}
.meter-track{width:100%;height:7px;background:var(--surface-2);border-radius:4px;overflow:hidden;border:1px solid var(--border)}
.meter-bar{height:100%;background:var(--accent);transition:width 0.25s ease}
.meter-bar.warn{background:var(--caution)}
.meter-bar.crit{background:var(--short)}

/* Positions & Allocation Split */
.positions-split{
  display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:14px;margin-bottom:14px;
}
.tbl-scroll{overflow-x:auto;max-height:340px;overflow-y:auto;border:1px solid var(--border);border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:12.5px;text-align:left}
th{
  position:sticky;top:0;z-index:2;background:var(--surface-2);color:var(--ink-2);
  padding:8px 10px;border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap;
}
td{
  padding:8px 10px;border-bottom:1px solid var(--border);color:var(--ink);vertical-align:middle;
}
tbody tr:hover td{background:var(--surface-2)}
.empty-cell{text-align:center;color:var(--muted);padding:20px 12px}

/* 58-Asset Universe Matrix */
.matrix-toolbar{
  display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px;
}
.coins-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:10px;
  max-height:560px;overflow-y:auto;padding-right:2px;
}
.coin-card{
  background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:11px 12px;
  display:flex;flex-direction:column;justify-content:space-between;gap:8px;min-width:0;
}
.coin-card.is-long{border-color:var(--long);background:var(--surface)}
.coin-card.is-short{border-color:var(--short);background:var(--surface)}
.coin-card.is-off{opacity:0.62}
.coin-hdr{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.coin-sym{font-size:14px;font-weight:700;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.tag{
  display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px;font-weight:600;
  border:1px solid var(--border);background:var(--surface-2);color:var(--ink-2);
}
.tag-long{background:var(--long-soft);color:var(--long);border-color:var(--long)}
.tag-short{background:var(--short-soft);color:var(--short);border-color:var(--short)}
.tag-caution{background:var(--caution-soft);color:var(--caution);border-color:var(--caution)}
.tag-accent{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}

.factor-strip{display:flex;flex-wrap:wrap;gap:4px}
.factor-pill{
  font-size:11px;padding:1px 5px;border-radius:3px;background:var(--surface-2);
  color:var(--ink-2);border:1px solid var(--border);
}
.coin-stats{display:grid;grid-template-columns:1fr 1fr;gap:4px 8px;font-size:12px;color:var(--ink-2)}
.coin-ctrl-row{
  display:grid;grid-template-columns:1fr 78px;gap:6px;padding-top:8px;border-top:1px solid var(--border);
}
.coin-ctrl-row select,.coin-ctrl-row input{padding:5px 7px;min-height:34px;font-size:12px;width:100%}

/* Secondary Operations Grid */
.ops-grid{
  display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:14px;margin-bottom:14px;
}
.news-list{list-style:none;display:flex;flex-direction:column;gap:6px;max-height:210px;overflow-y:auto}
.news-list li{
  padding:7px 10px;border-radius:5px;background:var(--surface-2);border:1px solid var(--border);
  font-size:12px;color:var(--ink);
}
.log-pre{
  background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:10px;
  font-size:11.5px;color:var(--ink);max-height:240px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;
}

.site-footer{
  margin-top:18px;padding-top:12px;border-top:1px solid var(--border);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;
  font-size:12px;color:var(--muted);
}

/* Accessible Modals */
.modal-backdrop{
  position:fixed;inset:0;background:var(--scrim);
  display:none;align-items:center;justify-content:center;padding:16px;z-index:1200;
}
.modal-backdrop.open{display:flex}
.modal-dialog{
  background:var(--surface);color:var(--ink);border:1px solid var(--control-border);
  border-radius:8px;padding:22px;width:100%;max-width:440px;box-shadow:var(--shadow-elev);
}
.modal-dialog h2{font-size:17px;margin-bottom:6px}
.modal-dialog p{font-size:13px;color:var(--muted);margin-bottom:14px}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px;flex-wrap:wrap}

.toast{
  position:fixed;bottom:18px;right:18px;z-index:1300;
  background:var(--ink);color:var(--surface);border:1px solid var(--control-border);
  padding:10px 16px;border-radius:6px;font-size:13px;font-weight:600;
  display:none;box-shadow:var(--shadow-elev);max-width:min(380px,calc(100vw - 36px));
}
.toast.err{background:var(--short);color:#FFFFFF;border-color:var(--short)}

/* Tablet Breakpoint (680px .. 1180px) */
@media(max-width:1180px){
  .overview-layout{grid-template-columns:1fr}
  .pipeline-rail{grid-template-columns:repeat(3,minmax(0,1fr))}
  .armor-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .positions-split{grid-template-columns:1fr}
  .ops-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}

/* Mobile Breakpoint (< 680px) */
@media(max-width:680px){
  .shell{padding:8px 10px 28px}
  .site-header{padding:10px 12px}
  button,select,input[type="number"],input[type="password"],input[type="text"],.nav-links a,.seg-btn,.coin-ctrl-row select,.coin-ctrl-row input{
    min-height:44px;font-size:13.5px;
  }
  .nav-toggle{display:inline-flex}
  .nav-links{display:none;width:100%;flex-direction:column;padding-top:6px}
  .nav-links.open{display:flex}
  .nav-links a{width:100%}
  .pipeline-rail{grid-template-columns:1fr}
  .armor-grid{grid-template-columns:1fr}
  .ops-grid{grid-template-columns:1fr}
  .canvas-stage{height:270px}
  .ctrl-cluster{width:100%}
  .ctrl-cluster .field-inline{width:100%;justify-content:space-between}
  .ctrl-cluster .field-inline select{flex:1}
}

@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}
</style>
</head>
<body>
<a class="skip-link" href="#mainContent">Перейти до основного вмісту</a>

<!-- Login Dialog -->
<div id="loginModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="loginTitle">
  <div class="modal-dialog">
    <h2 id="loginTitle">Авторизація термінала QuantCore</h2>
    <p>Введіть сервісний ключ доступу для перегляду телеметрії та керування виконанням.</p>
    <div style="margin-bottom:12px">
      <label for="loginPass" style="display:block;font-size:12.5px;font-weight:600;margin-bottom:5px">Пароль доступу</label>
      <input type="password" id="loginPass" autocomplete="current-password" placeholder="Введіть пароль сервера" style="width:100%" onkeydown="if(event.key==='Enter')doLogin()">
      <div id="loginErr" style="display:none;margin-top:6px;font-size:12px;color:var(--short);font-weight:600" role="alert"></div>
    </div>
    <div class="modal-actions">
      <button type="button" class="btn-primary" style="width:100%" onclick="doLogin()">Увійти в термінал</button>
    </div>
  </div>
</div>

<!-- Confirmation Dialog -->
<div id="confirmModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
  <div class="modal-dialog">
    <h2 id="confirmTitle">Підтвердження дії</h2>
    <p id="confirmBody">Ви впевнені?</p>
    <div class="modal-actions">
      <button type="button" id="confirmCancelBtn" onclick="closeConfirmModal()">Скасувати</button>
      <button type="button" id="confirmOkBtn" class="btn-danger">Підтвердити</button>
    </div>
  </div>
</div>

<!-- Pre-Flight Diagnostics Dialog -->
<div id="preflightModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="preflightTitle">
  <div class="modal-dialog" style="max-width:520px">
    <h2 id="preflightTitle">Передстартова перевірка сервера (Pre-Flight)</h2>
    <p>Фактичний зріз біржового шлюзу Binance USD-M, режиму позицій та ML-артефактів.</p>
    <dl class="ledger-dl mono" id="preflightList" style="padding:10px;background:var(--surface-2);border-radius:6px;border:1px solid var(--border)"></dl>
    <div class="modal-actions">
      <button type="button" class="btn-primary" onclick="closePreflightModal()">Закрити</button>
    </div>
  </div>
</div>

<div class="shell">
  <header class="site-header">
    <div class="hdr-top">
      <div class="brand-block">
        <div class="brand-row">
          <span class="brand-mark">QC</span>
          <h1>QuantCore Execution Terminal</h1>
          <span id="statusChip" class="status-chip"><span class="status-dot" aria-hidden="true"></span><span id="statusText">З'єднання...</span></span>
          <span id="envBadge" class="status-chip chip-caution mono">DEMO</span>
          <span id="cartridgeBadge" class="status-chip chip-accent mono">V6.1</span>
          <span id="regimeBadge" class="status-chip mono">CHOP</span>
          <span id="tierBadge" class="status-chip mono">N/A</span>
        </div>
        <div class="sys-strip mono">
          <span>Свічка (<span id="tfBadge">1h</span>): <strong id="candleBadge">очікування</strong></span>
          <span>До закриття 1h: <strong id="nextCandleTimer">00:00</strong></span>
          <span>Heartbeat: <strong id="hbBadge">N/A</strong></span>
          <span>Uptime: <strong id="uptimeBadge">N/A</strong></span>
          <span>RAM: <strong id="ramBadge">N/A</strong></span>
          <span>Диск: <strong id="diskBadge">N/A</strong></span>
        </div>
      </div>

      <div class="ctrl-cluster">
        <div class="field-inline">
          <label for="riskSelect">Профіль:</label>
          <select id="riskSelect" onchange="changeRiskProfile()">
            <option value="CONSERVATIVE">Conservative (1.6x)</option>
            <option value="OPTIMAL">Optimal (2.25x cap)</option>
            <option value="AGGRESSIVE">Aggressive (2.25x cap)</option>
            <option value="OVERDRIVE">Overdrive (Max)</option>
          </select>
        </div>
        <div class="field-inline">
          <label for="orchModeSelect">Режим:</label>
          <select id="orchModeSelect" onchange="changeRiskProfile()">
            <option value="PORTFOLIO_SYNERGY">Portfolio Synergy</option>
            <option value="SOLO_MAX">Solo Max</option>
          </select>
        </div>
        <button type="button" id="themeToggleBtn" aria-pressed="false" onclick="toggleTheme()">Темна тема</button>
        <button type="button" onclick="runPreflight()">Pre-Flight</button>
        <button type="button" class="btn-primary" onclick="triggerWakeup()">Перерахувати</button>
        <button type="button" class="btn-caution" id="pauseBtn" onclick="togglePause()">Пауза</button>
        <button type="button" class="btn-danger" onclick="confirmPanicClose()">Закрити все в USDT</button>
      </div>
    </div>
  </header>

  <nav class="sec-nav" aria-label="Навігація розділами термінала">
    <button type="button" class="nav-toggle" id="mobileNavBtn" aria-expanded="false" aria-controls="secNavList" onclick="toggleMobileNav()">Меню розділів</button>
    <ul class="nav-links" id="secNavList">
      <li><a href="#sec-overview" class="current" onclick="markNav(this)">Капітал і крива</a></li>
      <li><a href="#sec-pipeline" onclick="markNav(this)">Конвеєр і ризик-броня</a></li>
      <li><a href="#sec-positions" onclick="markNav(this)">Відкриті позиції та стопи</a></li>
      <li><a href="#sec-universe" onclick="markNav(this)">Матриця 58 пар</a></li>
      <li><a href="#sec-ops" onclick="markNav(this)">Виконання, новини та логи</a></li>
    </ul>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button type="button" onclick="downloadV2Zip()">Експорт ZIP</button>
      <button type="button" onclick="confirmCleanHistory()">Архівувати графік</button>
      <button type="button" onclick="confirmRestartServer()">Рестарт служби</button>
    </div>
  </nav>

  <div id="globalErrorBanner" class="alert-banner" role="alert">
    <span id="globalErrorText">Збій зв'язку з API сервера.</span>
    <button type="button" onclick="refreshAll()">Повторити запит</button>
  </div>

  <main id="mainContent">
    <!-- SECTION 1: FOCAL LEDGER + NATIVE EQUITY/DRAWDOWN CANVAS -->
    <section id="sec-overview" class="overview-layout" aria-labelledby="hdrOverview">
      <div class="panel panel-elevated">
        <div class="panel-hdr">
          <h2 id="hdrOverview">Зведений баланс і ризик</h2>
          <span class="panel-sub mono" id="calcLatencyBadge">calc: N/A</span>
        </div>
        <div class="focal-equity">
          <div class="focal-label">Поточний сумарний Equity (USDT)</div>
          <div class="focal-value mono" id="kpiEquity">Завантаження...</div>
          <div class="focal-delta mono" id="kpiPnlPct">Очікування зрізу з бази...</div>
        </div>
        <dl class="ledger-dl mono">
          <dt>Гаманець / uPnL</dt>
          <dd id="kpiWalletUpnl">N/A</dd>
          <dt>Чиста альфа проти BTC</dt>
          <dd id="kpiAlpha">N/A</dd>
          <dt>BTC Buy &amp; Hold</dt>
          <dd id="kpiBtcBh">N/A</dd>
          <dt>Валове / Нетто плече</dt>
          <dd id="kpiLev">0.00x / +0.00x</dd>
          <dt>Цільова бета режиму</dt>
          <dd id="kpiTargetBeta">N/A</dd>
          <dt>Sharpe / Calmar</dt>
          <dd id="kpiSharpeCalmar">N/A</dd>
          <dt>Історичний MaxDD</dt>
          <dd id="kpiMdd" class="neg-val">N/A</dd>
          <dt>Комісії / Операцій</dt>
          <dd id="kpiFees">N/A</dd>
          <dt>Maker частка / Сліпедж</dt>
          <dd id="kpiMakerSlip">N/A</dd>
          <dt>Середній спред / Фандінг</dt>
          <dd id="kpiSpreadFund">N/A</dd>
        </dl>
      </div>

      <div class="panel panel-elevated">
        <div class="panel-hdr">
          <div>
            <h2>Динаміка дохідності портфеля, BTC та просадки (%)</h2>
            <p class="panel-sub">Верхня площина показує кумулятивний ретерн у %, нижня показує підводну просадку від піку.</p>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <div class="seg-group" role="group" aria-label="Режим графіка">
              <button type="button" class="seg-btn active" id="tabEqMode" aria-pressed="true" onclick="switchChartMode('equity')">Портфель проти BTC</button>
              <button type="button" class="seg-btn" id="tabArenaMode" aria-pressed="false" onclick="switchChartMode('arena')">Shadow Arena</button>
            </div>
            <div class="seg-group" role="group" aria-label="Горизонт часу">
              <button type="button" class="seg-btn" id="rng-1" onclick="loadCharts(1)">24г</button>
              <button type="button" class="seg-btn" id="rng-7" onclick="loadCharts(7)">7д</button>
              <button type="button" class="seg-btn active" id="rng-30" onclick="loadCharts(30)">30д</button>
              <button type="button" class="seg-btn" id="rng-365" onclick="loadCharts(365)">365д</button>
            </div>
          </div>
        </div>
        <div class="canvas-stage" id="equityStage">
          <canvas id="equityCanvas" aria-label="Графік дохідності портфеля та підводної просадки"></canvas>
          <div id="equityTooltip" class="chart-tooltip mono"></div>
          <div id="equityPlaceholder" class="state-placeholder" style="display:flex">Завантаження часового ряду капіталу...</div>
        </div>
      </div>
    </section>

    <!-- SECTION 2: CAUSAL PIPELINE FLOW & HARD RISK ARMOR -->
    <section id="sec-pipeline" class="panel pipeline-section" aria-labelledby="hdrPipeline">
      <div class="panel-hdr">
        <div>
          <h2 id="hdrPipeline">Живий конвеєр прийняття рішень та захисна броня ризику</h2>
          <p class="panel-sub">Реальні лічильники останнього торгового кроку: від панелі свічок до виставлених біржових ордерів.</p>
        </div>
        <span class="mono panel-sub" id="leaderSummary">Флагман книги: N/A</span>
      </div>

      <div class="pipeline-rail">
        <div class="pipe-step">
          <span class="pipe-kicker">1. Всесвіт і ширина ринку</span>
          <span class="pipe-main mono" id="pipeUniverse">0 пар</span>
          <span class="pipe-note mono" id="pipeBreadth">Breadth: N/A | BTC EMA200: N/A</span>
        </div>
        <div class="pipe-step">
          <span class="pipe-kicker">2. Режим і тір капіталу</span>
          <span class="pipe-main mono" id="pipeRegimeTier">N/A</span>
          <span class="pipe-note mono" id="pipeDispersion">Дисперсія альфи: N/A</span>
        </div>
        <div class="pipe-step">
          <span class="pipe-kicker">3. Розподіл рукавів (Gross)</span>
          <span class="pipe-main mono" id="pipePodsGross">B: 0.00x</span>
          <span class="pipe-note mono" id="pipePodsSub">Regime/A: 0.00x | S/C: 0.00x</span>
        </div>
        <div class="pipe-step">
          <span class="pipe-kicker">4. Передстартові фільтри</span>
          <span class="pipe-main mono" id="pipeSkippedTotal">0 відсіяно</span>
          <span class="pipe-note mono" id="pipeSkippedBreak">spread: 0 | minNot: 0 | deadzone: 0</span>
        </div>
        <div class="pipe-step">
          <span class="pipe-kicker">5. Жива книга та кулдауни</span>
          <span class="pipe-main mono" id="pipeLivePos">0 відкритих</span>
          <span class="pipe-note mono" id="pipeCooldowns">48h стоп-кулдауни: 0</span>
        </div>
      </div>

      <div class="armor-grid">
        <div class="armor-meter">
          <div class="meter-hdr"><span>Денна просадка (ліміт <span id="limDailyLbl">5.0%</span>)</span><strong class="mono" id="valDailyDd">0.00%</strong></div>
          <div class="meter-track"><div class="meter-bar" id="barDailyDd" style="width:0%"></div></div>
        </div>
        <div class="armor-meter">
          <div class="meter-hdr"><span>Просадка від піку (стоп <span id="limTotalLbl">20.0%</span>)</span><strong class="mono" id="valPeakDd">0.00%</strong></div>
          <div class="meter-track"><div class="meter-bar" id="barPeakDd" style="width:0%"></div></div>
        </div>
        <div class="armor-meter">
          <div class="meter-hdr"><span>Валове плече (стеля <span id="limGrossLbl">2.25x</span>)</span><strong class="mono" id="valGrossCap">0.00x</strong></div>
          <div class="meter-track"><div class="meter-bar" id="barGrossCap" style="width:0%"></div></div>
        </div>
        <div class="armor-meter">
          <div class="meter-hdr"><span>Дисбаланс L/S відносно цілі</span><strong class="mono" id="valImbalance">0.00x</strong></div>
          <div class="meter-track"><div class="meter-bar" id="barImbalance" style="width:0%"></div></div>
        </div>
      </div>
    </section>

    <!-- SECTION 3: ACTIVE POSITIONS & EXCHANGE STOP-LOSSES + DIVERGING CANVAS -->
    <section id="sec-positions" class="positions-split" aria-labelledby="hdrPositions">
      <div class="panel">
        <div class="panel-hdr">
          <div>
            <h2 id="hdrPositions">Активні позиції та біржові STOP_MARKET ордери</h2>
            <p class="panel-sub">Фактичні контракти на біржі, ціна входу, активний захисний стоп, ставка фандінгу та uPnL.</p>
          </div>
          <span class="mono panel-sub" id="activeBookSummary">L: +0.00x | S: -0.00x</span>
        </div>
        <div class="tbl-scroll">
          <table>
            <thead>
              <tr>
                <th>Пара</th>
                <th>Напрям / Рукав</th>
                <th>Нотіонал</th>
                <th>Факт / Ціль</th>
                <th>Вхід / Ціна</th>
                <th>Активний SL (відст.)</th>
                <th>Фандінг 8h</th>
                <th>uPnL</th>
              </tr>
            </thead>
            <tbody id="activePosBody">
              <tr><td colspan="8" class="empty-cell">Завантаження відкритих позицій...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <div class="panel-hdr">
          <div>
            <h2>Вектор алокації: цільова вага моделі проти факту біржі</h2>
            <p class="panel-sub">Стовпчик показує цільову вагу, ромб позначає фактичну вагу відкритої позиції.</p>
          </div>
        </div>
        <div class="canvas-stage compact" id="allocStage">
          <canvas id="allocCanvas" aria-label="Діаграма цільових та фактичних ваг активів"></canvas>
          <div id="allocPlaceholder" class="state-placeholder" style="display:flex">Портфель у 100% USDT кеші. Натисніть «Перерахувати» для позачергової перевірки сигналів.</div>
        </div>
      </div>
    </section>

    <!-- SHADOW ARENA LEADERBOARD -->
    <section class="panel" style="margin-bottom:14px" aria-labelledby="hdrArena">
      <div class="panel-hdr">
        <div>
          <h2 id="hdrArena">Shadow Arena: паралельне порівняння віртуальних профілів на живих свічках</h2>
          <p class="panel-sub">Усі віртуальні портфелі оцінюються синхронно на тих самих реальних котируваннях і спредах.</p>
        </div>
        <span class="mono panel-sub" id="vCapBadge">Віртуальний ліміт: N/A</span>
      </div>
      <div class="tbl-scroll" style="max-height:220px">
        <table>
          <thead>
            <tr>
              <th>Місце</th>
              <th>Профіль моделі</th>
              <th>Старт</th>
              <th>Поточний Equity</th>
              <th>Дохідність</th>
              <th>MaxDD</th>
              <th>Gross / Net</th>
              <th>Позицій</th>
              <th>Угод (Комісії)</th>
            </tr>
          </thead>
          <tbody id="arenaBody">
            <tr><td colspan="9" class="empty-cell">Очікування даних Shadow Arena...</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- SECTION 4: 58-ASSET UNIVERSE RADAR & MANUAL OVERRIDES -->
    <section id="sec-universe" class="panel" aria-labelledby="hdrUniverse">
      <div class="panel-hdr">
        <div>
          <h2 id="hdrUniverse">Матриця всесвіту та індивідуальні обмеження пар</h2>
          <p class="panel-sub">Керування дозволеним напрямком (Auto, Long Only, Short Only, Off) та пріоритетом капіталу для кожної монети.</p>
        </div>
        <span class="mono panel-sub" id="matrixCountBadge">0 пар</span>
      </div>

      <div class="matrix-toolbar">
        <div class="field-inline">
          <label for="coinSearch">Пошук пари:</label>
          <input type="text" id="coinSearch" placeholder="Напр. SOLUSDT" oninput="renderCoinsMatrix()">
        </div>
        <div class="seg-group" role="group" aria-label="Фільтр валют">
          <button type="button" class="seg-btn active" id="flt-all" onclick="setCoinFilter('all')">Усі</button>
          <button type="button" class="seg-btn" id="flt-active" onclick="setCoinFilter('active')">У книзі</button>
          <button type="button" class="seg-btn" id="flt-long" onclick="setCoinFilter('long')">Longs</button>
          <button type="button" class="seg-btn" id="flt-short" onclick="setCoinFilter('short')">Shorts</button>
          <button type="button" class="seg-btn" id="flt-cooldown" onclick="setCoinFilter('cooldown')">Під 48h кулдауном</button>
          <button type="button" class="seg-btn" id="flt-majors" onclick="setCoinFilter('majors')">Majors</button>
        </div>
      </div>

      <div class="coins-grid" id="coinsGrid" aria-live="polite"></div>
    </section>

    <!-- SECTION 5: EXECUTION TELEMETRY, TRADES, NEWS & LOGS -->
    <section id="sec-ops" class="ops-grid" aria-label="Журнали виконання, новин та системних логів">
      <div class="panel">
        <div class="panel-hdr">
          <h2>Мікроструктура виконання ордерів</h2>
          <button type="button" onclick="loadV2Telemetry()">Оновити</button>
        </div>
        <div class="tbl-scroll" style="max-height:280px">
          <table>
            <thead>
              <tr><th>Час</th><th>Пара</th><th>Рукав</th><th>Тип</th><th>Slip bps</th><th>Спред</th><th>Статус</th></tr>
            </thead>
            <tbody id="v2ExecBody">
              <tr><td colspan="7" class="empty-cell">Завантаження телеметрії ордерів...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <div class="panel-hdr">
          <h2>Журнал закритих та виконаних угод</h2>
          <div class="field-inline">
            <label for="tradeSymFilter" class="sr-only">Фільтр валюти у журналі угод</label>
            <select id="tradeSymFilter" aria-label="Фільтр валюти у журналі угод" onchange="loadTrades()">
              <option value="">Усі валюти</option>
            </select>
          </div>
        </div>
        <div class="tbl-scroll" style="max-height:280px">
          <table>
            <thead>
              <tr><th>Час</th><th>Пара</th><th>Дія</th><th>Ціна</th><th>Net PnL</th></tr>
            </thead>
            <tbody id="tradesBody">
              <tr><td colspan="5" class="empty-cell">Завантаження історії угод...</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel" style="display:flex;flex-direction:column;gap:12px">
        <div>
          <div class="panel-hdr">
            <h2>Моніторинг новин та R5 Geo-Shock</h2>
            <div style="display:flex;align-items:center;gap:6px">
              <span class="mono panel-sub">Sent: <strong id="newsVal">0.00</strong> | Ризик шоку: <strong id="shockProbVal">0%</strong></span>
              <span id="geoShockBadge" class="tag tag-short" style="display:none">R5 SHOCK</span>
              <button type="button" onclick="refreshNews()">Оновити RSS</button>
            </div>
          </div>
          <ul class="news-list" id="newsList">
            <li style="color:var(--muted)">Завантаження свіжих заголовків RSS...</li>
          </ul>
        </div>

        <div>
          <div class="panel-hdr">
            <h2>Системний лог та заміна моделі (.joblib)</h2>
            <div style="display:flex;gap:6px;align-items:center">
              <label for="logSearch" class="sr-only">Фільтр рядків логу</label>
              <input type="text" id="logSearch" aria-label="Фільтр рядків логу" placeholder="Фільтр логу..." style="width:125px;padding:4px 8px;min-height:32px" oninput="renderFilteredLogs()">
              <button type="button" onclick="loadLogs()">Оновити</button>
            </div>
          </div>
          <pre class="log-pre mono" id="logBox">Завантаження останніх рядків trading_bot.log...</pre>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
            <label for="joblibFile" style="font-size:12px;font-weight:600;color:var(--muted)">Пакет моделі (.joblib):</label>
            <input type="file" id="joblibFile" accept=".joblib" style="font-size:12px;flex:1;min-width:160px">
            <button type="button" class="btn-primary" onclick="uploadCartridge()">Завантажити модель</button>
            <button type="button" onclick="confirmRollbackCartridge()">Відкотити</button>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <span>QuantCore Execution Server. Усі показники відображають виключно реальну телеметрію поточного екземпляра.</span>
    <span class="mono" id="footerSyncStamp">Остання синхронізація UI: очікування</span>
  </footer>
</div>

<div class="toast" id="toast" role="status" aria-live="polite">Виконано</div>

<script>
const MAJORS_SET = new Set(['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT']);
let currentChartDays = 30;
let chartViewMode = 'equity';
let lastChartPayload = null;
let isPausedState = false;
let cachedCoins = [];
let cachedLogs = [];
let coinFilter = 'all';
let confirmCallback = null;
let lastFocusedBeforeModal = null;

/* Theme Persistence (Light Default, Full Dark Parity) */
function applyTheme(theme){
  const clean = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', clean);
  localStorage.setItem('qc_theme', clean);
  const btn = document.getElementById('themeToggleBtn');
  if(btn){
    btn.setAttribute('aria-pressed', clean === 'dark' ? 'true' : 'false');
    btn.textContent = clean === 'dark' ? 'Світла тема' : 'Темна тема';
  }
  renderMainChart();
  renderAllocationVector(cachedCoins);
}
function toggleTheme(){
  const cur = document.documentElement.getAttribute('data-theme') || 'light';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
}
(function initSavedTheme(){
  const saved = localStorage.getItem('qc_theme');
  applyTheme(saved === 'dark' ? 'dark' : 'light');
})();

function cssVar(name){
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function toggleMobileNav(){
  const list = document.getElementById('secNavList');
  const btn = document.getElementById('mobileNavBtn');
  const open = !list.classList.contains('open');
  list.classList.toggle('open', open);
  btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function markNav(el){
  document.querySelectorAll('#secNavList a').forEach(a => a.classList.remove('current'));
  el.classList.add('current');
  const list = document.getElementById('secNavList');
  const btn = document.getElementById('mobileNavBtn');
  if(list.classList.contains('open')){
    list.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
  }
}

/* Accessible Modal Management + Escape Key */
function openConfirmModal(title, body, okLabel, isDanger, onConfirm){
  lastFocusedBeforeModal = document.activeElement;
  confirmCallback = onConfirm;
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmBody').textContent = body;
  const okBtn = document.getElementById('confirmOkBtn');
  okBtn.textContent = okLabel;
  okBtn.className = isDanger ? 'btn-danger' : 'btn-primary';
  okBtn.onclick = async () => {
    closeConfirmModal();
    if(confirmCallback) await confirmCallback();
  };
  document.getElementById('confirmModal').classList.add('open');
  document.getElementById('confirmCancelBtn').focus();
}
function closeConfirmModal(){
  document.getElementById('confirmModal').classList.remove('open');
  confirmCallback = null;
  if(lastFocusedBeforeModal && typeof lastFocusedBeforeModal.focus === 'function') lastFocusedBeforeModal.focus();
}
function closePreflightModal(){
  document.getElementById('preflightModal').classList.remove('open');
  if(lastFocusedBeforeModal && typeof lastFocusedBeforeModal.focus === 'function') lastFocusedBeforeModal.focus();
}
document.addEventListener('keydown', (ev) => {
  if(ev.key === 'Escape'){
    if(document.getElementById('confirmModal').classList.contains('open')) closeConfirmModal();
    else if(document.getElementById('preflightModal').classList.contains('open')) closePreflightModal();
  }
});

/* 1h Candle Countdown */
function tickCandleCountdown(){
  if(document.hidden) return;
  const now = new Date();
  const remSec = 3600 - (now.getUTCMinutes() * 60 + now.getUTCSeconds()) + 4;
  const mm = String(Math.floor(remSec / 60)).padStart(2, '0');
  const ss = String(remSec % 60).padStart(2, '0');
  const el = document.getElementById('nextCandleTimer');
  if(el) el.textContent = `${mm}:${ss}`;
}
setInterval(tickCandleCountdown, 1000);
tickCandleCountdown();

function showToast(msg, isErr=false){
  const t = document.getElementById('toast');
  t.className = isErr ? 'toast err' : 'toast';
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(t._tid);
  t._tid = setTimeout(() => { t.style.display = 'none'; }, 3200);
}

function getHeaders(){
  const tok = localStorage.getItem('qc_token') || '';
  return {'Content-Type':'application/json', 'X-Api-Key': tok};
}

async function apiFetch(url, opts={}){
  opts.headers = Object.assign(getHeaders(), opts.headers || {});
  const resp = await fetch(url, opts);
  if(resp.status === 401){
    document.getElementById('loginModal').classList.add('open');
    document.getElementById('loginPass').focus();
    throw new Error('Unauthorized');
  }
  if(!resp.ok){
    throw new Error(`HTTP ${resp.status}`);
  }
  document.getElementById('globalErrorBanner').style.display = 'none';
  return resp.json();
}

async function doLogin(){
  const pwd = document.getElementById('loginPass').value;
  const errEl = document.getElementById('loginErr');
  errEl.style.display = 'none';
  try{
    const r = await fetch('/api/v1/auth/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({password: pwd})
    });
    if(r.ok){
      const d = await r.json();
      localStorage.setItem('qc_token', d.token);
      document.getElementById('loginModal').classList.remove('open');
      refreshAll();
    } else {
      errEl.textContent = 'Невірний пароль доступу. Перевірте ключ та спробуйте ще раз.';
      errEl.style.display = 'block';
    }
  }catch(e){
    errEl.textContent = 'Сервер тимчасово недоступний.';
    errEl.style.display = 'block';
  }
}

function fmtDuration(sec){
  if(sec === null || sec === undefined || !Number.isFinite(Number(sec))) return 'N/A';
  const s = Math.max(0, Math.round(Number(sec)));
  if(s < 60) return `${s}с`;
  if(s < 3600) return `${Math.floor(s/60)}хв ${s%60}с`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}год ${m}хв`;
}

function escapeHtml(str){
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* Native Zero-Dependency HiDPI Canvas Charts */
function prepareCanvas(canvas){
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(240, Math.floor(rect.width));
  const h = Math.max(180, Math.floor(rect.height));
  if(canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)){
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return {ctx, w, h};
}

let equityHoverMeta = null;

function renderMainChart(){
  const canvas = document.getElementById('equityCanvas');
  const ph = document.getElementById('equityPlaceholder');
  const tip = document.getElementById('equityTooltip');
  if(!canvas || !ph) return;
  tip.style.display = 'none';

  if(!lastChartPayload || !lastChartPayload.chart){
    ph.textContent = 'Очікування накопичення свічок історії для побудови кривої.';
    ph.style.display = 'flex';
    return;
  }

  const ch = lastChartPayload.chart;
  const gridCol = cssVar('--chart-grid');
  const zeroCol = cssVar('--chart-zero');
  const mutedCol = cssVar('--muted');
  const inkCol = cssVar('--ink');
  const longCol = cssVar('--long');
  const shortCol = cssVar('--short');
  const accentCol = cssVar('--accent');
  const cautionCol = cssVar('--caution');

  if(chartViewMode === 'arena'){
    const aMap = ch.arena_series || {};
    const ids = Object.keys(aMap).filter(k => aMap[k] && Array.isArray(aMap[k].ret_pct) && aMap[k].ret_pct.length > 0);
    if(!ids.length){
      ph.textContent = 'Shadow Arena ще не записала історичних точок. Дочекайтеся закриття першої свічки.';
      ph.style.display = 'flex';
      return;
    }
    ph.style.display = 'none';
    const {ctx, w, h} = prepareCanvas(canvas);
    const pad = {l: 52, r: 16, t: 26, b: 28};
    const pw = Math.max(40, w - pad.l - pad.r);
    const phgt = Math.max(40, h - pad.t - pad.b);

    let minY = 0, maxY = 0;
    ids.forEach(id => {
      aMap[id].ret_pct.forEach(v => {
        const n = Number(v || 0);
        if(n < minY) minY = n;
        if(n > maxY) maxY = n;
      });
    });
    if(maxY - minY < 1.0){ maxY += 0.5; minY -= 0.5; }
    const spanY = maxY - minY;
    const yPx = v => pad.t + (1 - (v - minY) / spanY) * phgt;

    ctx.font = '11px "IBM Plex Mono", monospace';
    ctx.fillStyle = mutedCol;
    for(let g = 0; g <= 4; g++){
      const val = minY + (spanY * g) / 4;
      const gy = yPx(val);
      ctx.strokeStyle = gridCol;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
      ctx.textAlign = 'right';
      ctx.fillText(`${val >= 0 ? '+' : ''}${val.toFixed(1)}%`, pad.l - 6, gy + 4);
    }
    if(minY <= 0 && maxY >= 0){
      const zy = yPx(0);
      ctx.strokeStyle = zeroCol; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(pad.l, zy); ctx.lineTo(w - pad.r, zy); ctx.stroke();
      ctx.setLineDash([]);
    }

    const palette = [accentCol, longCol, cautionCol, shortCol, inkCol, mutedCol];
    ids.forEach((id, idx) => {
      const ys = aMap[id].ret_pct;
      const col = palette[idx % palette.length];
      ctx.strokeStyle = col;
      ctx.lineWidth = idx === 0 ? 2.2 : 1.5;
      ctx.beginPath();
      ys.forEach((v, i) => {
        const x = pad.l + (ys.length === 1 ? pw / 2 : (i / (ys.length - 1)) * pw);
        const y = yPx(Number(v || 0));
        if(i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillStyle = col;
      ctx.textAlign = 'left';
      ctx.fillText(id, pad.l + (idx * 105) % Math.max(120, pw - 80), 15);
    });
    equityHoverMeta = null;
    return;
  }

  const times = ch.times || [];
  const eqRet = (ch.equity_ret_pct || []).map(Number);
  const btcRet = (ch.btc_ret_pct || []).map(Number);
  const ddArr = (ch.drawdown_pct || []).map(Number);

  if(!times.length || !eqRet.length){
    ph.textContent = 'Немає записаних свічок у вибраному діапазоні. Натисніть «Перерахувати» або оберіть довший період.';
    ph.style.display = 'flex';
    return;
  }
  ph.style.display = 'none';

  const {ctx, w, h} = prepareCanvas(canvas);
  const pad = {l: 54, r: 16, t: 22, b: 26};
  const pw = Math.max(40, w - pad.l - pad.r);
  const gapMid = 14;
  const topH = Math.floor((h - pad.t - pad.b - gapMid) * 0.70);
  const botTop = pad.t + topH + gapMid;
  const botH = Math.max(38, h - botTop - pad.b);

  let minR = Math.min(0, ...eqRet, ...(btcRet.length ? btcRet : [0]));
  let maxR = Math.max(0, ...eqRet, ...(btcRet.length ? btcRet : [0]));
  if(maxR - minR < 0.8){ maxR += 0.4; minR -= 0.4; }
  const spanR = maxR - minR;

  let minDd = Math.min(-1.0, ...(ddArr.length ? ddArr : [-1.0]));
  const maxDd = 0.0;
  const spanDd = Math.max(0.5, maxDd - minDd);

  const xPx = i => pad.l + (times.length === 1 ? pw / 2 : (i / (times.length - 1)) * pw);
  const yTop = v => pad.t + (1 - (v - minR) / spanR) * topH;
  const yBot = v => botTop + (1 - (v - minDd) / spanDd) * botH;

  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.fillStyle = mutedCol;
  for(let g = 0; g <= 3; g++){
    const vr = minR + (spanR * g) / 3;
    const gy = yTop(vr);
    ctx.strokeStyle = gridCol; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
    ctx.textAlign = 'right';
    ctx.fillText(`${vr >= 0 ? '+' : ''}${vr.toFixed(1)}%`, pad.l - 6, gy + 4);
  }
  if(minR <= 0 && maxR >= 0){
    const zy = yTop(0);
    ctx.strokeStyle = zeroCol; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, zy); ctx.lineTo(w - pad.r, zy); ctx.stroke();
    ctx.setLineDash([]);
  }

  /* BTC Dashed Benchmark */
  if(btcRet.length === times.length){
    ctx.strokeStyle = cautionCol; ctx.lineWidth = 1.4; ctx.setLineDash([5, 4]);
    ctx.beginPath();
    btcRet.forEach((v, i) => {
      const x = xPx(i), y = yTop(v);
      if(i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  /* Strategy Equity Curve */
  ctx.strokeStyle = accentCol; ctx.lineWidth = 2.2;
  ctx.beginPath();
  eqRet.forEach((v, i) => {
    const x = xPx(i), y = yTop(v);
    if(i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  if(times.length <= 2){
    eqRet.forEach((v, i) => {
      ctx.fillStyle = accentCol;
      ctx.beginPath(); ctx.arc(xPx(i), yTop(v), 4, 0, Math.PI * 2); ctx.fill();
    });
  }

  /* Underwater Drawdown Pane */
  ctx.strokeStyle = gridCol; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad.l, botTop); ctx.lineTo(w - pad.r, botTop); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(pad.l, botTop + botH); ctx.lineTo(w - pad.r, botTop + botH); ctx.stroke();
  ctx.fillStyle = mutedCol; ctx.textAlign = 'right';
  ctx.fillText('0.0%', pad.l - 6, botTop + 8);
  ctx.fillText(`${minDd.toFixed(1)}%`, pad.l - 6, botTop + botH);

  if(ddArr.length === times.length){
    ctx.fillStyle = cssVar('--short-soft');
    ctx.beginPath();
    ctx.moveTo(xPx(0), yBot(0));
    ddArr.forEach((v, i) => ctx.lineTo(xPx(i), yBot(v)));
    ctx.lineTo(xPx(ddArr.length - 1), yBot(0));
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = shortCol; ctx.lineWidth = 1.3;
    ctx.beginPath();
    ddArr.forEach((v, i) => {
      const x = xPx(i), y = yBot(v);
      if(i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  /* X-axis ticks & inline legend */
  ctx.fillStyle = mutedCol; ctx.textAlign = 'center';
  const tickCnt = Math.min(times.length, 5);
  for(let k = 0; k < tickCnt; k++){
    const idx = tickCnt === 1 ? 0 : Math.round((k / (tickCnt - 1)) * (times.length - 1));
    ctx.fillText(String(times[idx] || '').slice(5, 16), xPx(idx), h - 6);
  }
  ctx.textAlign = 'left';
  ctx.fillStyle = accentCol; ctx.fillText('Портфель %', pad.l, 14);
  ctx.fillStyle = cautionCol; ctx.fillText('BTC B&H %', pad.l + 96, 14);
  ctx.fillStyle = shortCol; ctx.fillText('Drawdown %', pad.l + 188, 14);

  equityHoverMeta = {times, eqRet, btcRet, ddArr, pad, pw, w};
}

(function bindEquityInteractions(){
  const stage = document.getElementById('equityStage');
  const tip = document.getElementById('equityTooltip');
  if(!stage || !tip) return;
  function handlePoint(clientX){
    if(!equityHoverMeta || !equityHoverMeta.times.length) return;
    const rect = stage.getBoundingClientRect();
    const relX = clientX - rect.left - equityHoverMeta.pad.l;
    const frac = Math.max(0, Math.min(1, relX / Math.max(1, equityHoverMeta.pw)));
    const idx = Math.round(frac * (equityHoverMeta.times.length - 1));
    const tStr = equityHoverMeta.times[idx] || '';
    const er = Number(equityHoverMeta.eqRet[idx] || 0);
    const br = Number(equityHoverMeta.btcRet[idx] || 0);
    const dd = Number(equityHoverMeta.ddArr[idx] || 0);
    tip.innerHTML = `<strong>${escapeHtml(tStr)}</strong><br>Портфель: ${er>=0?'+':''}${er.toFixed(2)}%<br>BTC: ${br>=0?'+':''}${br.toFixed(2)}%<br>DD: ${dd.toFixed(2)}%`;
    tip.style.display = 'block';
    const leftPx = Math.min(rect.width - 190, Math.max(8, clientX - rect.left + 10));
    tip.style.left = `${leftPx}px`;
    tip.style.top = '28px';
  }
  stage.addEventListener('mousemove', e => handlePoint(e.clientX));
  stage.addEventListener('touchstart', e => { if(e.touches[0]) handlePoint(e.touches[0].clientX); }, {passive:true});
  stage.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
})();

function renderAllocationVector(coins){
  const canvas = document.getElementById('allocCanvas');
  const ph = document.getElementById('allocPlaceholder');
  if(!canvas || !ph) return;

  const active = (coins || []).filter(c => Math.abs(Number(c.target_weight || 0)) > 0.003 || Math.abs(Number(c.realized_weight || 0)) > 0.003);
  active.sort((a, b) => Number(b.target_weight || b.realized_weight || 0) - Number(a.target_weight || a.realized_weight || 0));

  const longSum = active.reduce((acc, c) => acc + Math.max(0, Number(c.target_weight || 0)), 0);
  const shortSum = active.reduce((acc, c) => acc + Math.min(0, Number(c.target_weight || 0)), 0);
  const actPos = (coins || []).filter(c => Math.abs(c.current_pos_qty) > 0).length;
  const badge = document.getElementById('activeBookSummary');
  if(badge) badge.textContent = `L: +${longSum.toFixed(2)}x | S: ${shortSum.toFixed(2)}x | Відкрито: ${actPos}`;

  if(!active.length){
    ph.style.display = 'flex';
    return;
  }
  ph.style.display = 'none';

  const topRows = active.slice(0, 12);
  const {ctx, w, h} = prepareCanvas(canvas);
  const pad = {l: 58, r: 48, t: 14, b: 18};
  const pw = Math.max(40, w - pad.l - pad.r);
  const phgt = Math.max(40, h - pad.t - pad.b);
  const maxAbs = Math.max(0.10, ...topRows.map(c => Math.max(Math.abs(Number(c.target_weight||0)), Math.abs(Number(c.realized_weight||0)))));
  const midX = pad.l + pw / 2;
  const rowH = phgt / topRows.length;

  ctx.strokeStyle = cssVar('--chart-zero');
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(midX, pad.t); ctx.lineTo(midX, h - pad.b); ctx.stroke();

  ctx.font = '11px "IBM Plex Mono", monospace';
  const longCol = cssVar('--long');
  const shortCol = cssVar('--short');
  const inkCol = cssVar('--ink');
  const mutedCol = cssVar('--muted');

  topRows.forEach((c, idx) => {
    const cy = pad.t + idx * rowH + rowH * 0.5;
    const tw = Number(c.target_weight || 0);
    const rw = Number(c.realized_weight || 0);
    const barW = (Math.abs(tw) / maxAbs) * (pw * 0.46);
    const bx = tw >= 0 ? midX : midX - barW;
    const barH = Math.max(7, Math.min(15, rowH * 0.58));

    ctx.fillStyle = tw >= 0 ? longCol : shortCol;
    ctx.fillRect(bx, cy - barH / 2, Math.max(1.5, barW), barH);

    /* Diamond marker for actual exchange weight */
    const rx = midX + (rw / maxAbs) * (pw * 0.46);
    ctx.fillStyle = inkCol;
    ctx.beginPath();
    ctx.moveTo(rx, cy - 4.5);
    ctx.lineTo(rx + 4.5, cy);
    ctx.lineTo(rx, cy + 4.5);
    ctx.lineTo(rx - 4.5, cy);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = inkCol;
    ctx.textAlign = 'right';
    ctx.fillText(c.symbol.replace('USDT',''), pad.l - 6, cy + 3.5);
    ctx.fillStyle = mutedCol;
    ctx.textAlign = 'left';
    ctx.fillText(`${tw>=0?'+':''}${tw.toFixed(2)}x`, w - pad.r + 4, cy + 3.5);
  });
}

window.addEventListener('resize', () => {
  renderMainChart();
  renderAllocationVector(cachedCoins);
});

function renderActivePositionsTable(coins){
  const tb = document.getElementById('activePosBody');
  if(!tb) return;
  const openList = (coins || []).filter(c => Math.abs(Number(c.current_pos_qty || 0)) > 0);
  openList.sort((a, b) => Number(b.notional_usdt || 0) - Number(a.notional_usdt || 0));

  if(!openList.length){
    tb.innerHTML = '<tr><td colspan="8" class="empty-cell">На біржі немає відкритих позицій (100% USDT кеш). Нові позиції з\'являться після планового ребалансу або натискання «Перерахувати».</td></tr>';
    return;
  }

  tb.innerHTML = openList.map(c => {
    const isLong = Number(c.current_pos_qty) > 0;
    const dirTag = isLong ? '<span class="tag tag-long">LONG</span>' : '<span class="tag tag-short">SHORT</span>';
    const sb = escapeHtml((c.sleeve_book || 'CORE').replace('SLEEVE_', ''));
    const px = Number(c.price || 0);
    const ep = Number(c.entry_price || 0);
    const sl = Number(c.s_stop_px || c.active_sl_price || 0);
    let slText = 'N/A';
    if(sl > 0 && px > 0){
      const distPct = Math.abs(px - sl) / px * 100;
      slText = `$${sl.toLocaleString(undefined,{maximumFractionDigits:4})} (${distPct.toFixed(1)}%)`;
    } else if(sl > 0){
      slText = `$${sl.toLocaleString(undefined,{maximumFractionDigits:4})}`;
    }
    const fr = c.funding_rate;
    const frText = (fr !== null && fr !== undefined && Number.isFinite(Number(fr)))
      ? `${Number(fr)*100 >= 0 ? '+' : ''}${(Number(fr)*100).toFixed(4)}%`
      : 'N/A';
    const upnl = Number(c.unrealized_pnl || 0);
    const upnlCls = upnl >= 0 ? 'pos-val' : 'neg-val';
    const rw = Number(c.realized_weight || 0);
    const tw = Number(c.target_weight || 0);
    return `<tr class="mono">
      <td><strong>${escapeHtml(c.symbol)}</strong></td>
      <td>${dirTag} <span class="tag">${sb}</span></td>
      <td>$${Number(c.notional_usdt||0).toFixed(2)}</td>
      <td>${rw>=0?'+':''}${rw.toFixed(2)}x / ${tw>=0?'+':''}${tw.toFixed(2)}x</td>
      <td>$${ep ? ep.toLocaleString(undefined,{maximumFractionDigits:4}) : 'N/A'} / $${px ? px.toLocaleString(undefined,{maximumFractionDigits:4}) : 'N/A'}</td>
      <td>${slText}</td>
      <td>${frText}</td>
      <td class="${upnlCls}"><strong>${upnl>=0?'+':''}$${upnl.toFixed(2)}</strong></td>
    </tr>`;
  }).join('');
}

function setCoinFilter(flt){
  coinFilter = flt;
  ['all','active','long','short','cooldown','majors'].forEach(k => {
    const el = document.getElementById('flt-' + k);
    if(el) el.className = 'seg-btn' + (k === flt ? ' active' : '');
  });
  renderCoinsMatrix();
}

function renderCoinsMatrix(coinsArg){
  if(coinsArg) cachedCoins = coinsArg;
  const grid = document.getElementById('coinsGrid');
  if(!grid) return;
  const q = (document.getElementById('coinSearch').value || '').trim().toUpperCase();
  const nowMs = Date.now();

  const filtered = cachedCoins.filter(c => {
    if(q && !c.symbol.includes(q)) return false;
    const tw = Number(c.target_weight || 0), rw = Number(c.realized_weight || 0);
    const cdActive = Number(c.cooldown_until_ms || 0) > nowMs;
    if(coinFilter === 'active') return Math.abs(c.current_pos_qty) > 0 || Math.abs(tw) > 0.004 || Math.abs(rw) > 0.004;
    if(coinFilter === 'long') return c.current_pos_qty > 0 || tw > 0.004;
    if(coinFilter === 'short') return c.current_pos_qty < 0 || tw < -0.004;
    if(coinFilter === 'cooldown') return cdActive;
    if(coinFilter === 'majors') return MAJORS_SET.has(c.symbol);
    return true;
  });

  document.getElementById('matrixCountBadge').textContent = `Показано ${filtered.length} із ${cachedCoins.length} пар`;

  if(!filtered.length){
    grid.innerHTML = '<div class="panel" style="grid-column:1/-1;text-align:center;color:var(--muted)">За вибраним фільтром пар не знайдено. Скиньте пошук або перемкніть вкладку «Усі».</div>';
    return;
  }

  filtered.sort((a, b) => (Math.abs(b.notional_usdt) - Math.abs(a.notional_usdt)) || (Math.abs(b.target_weight) - Math.abs(a.target_weight)));

  grid.innerHTML = filtered.map(c => {
    const sym = escapeHtml(c.symbol);
    const hasPos = Math.abs(c.current_pos_qty) > 0;
    const cardCls = 'coin-card' + (hasPos ? (c.current_pos_qty > 0 ? ' is-long' : ' is-short') : '') + (!c.enabled ? ' is-off' : '');
    const sb = String(c.sleeve_book || '').replace('SLEEVE_', '');
    const sbBadge = sb && sb !== 'FLAT' ? `<span class="tag tag-accent">${escapeHtml(sb)}</span>` : '';
    const cdRemH = Math.max(0, (Number(c.cooldown_until_ms || 0) - nowMs) / 3600000);
    const cdBadge = cdRemH > 0 ? `<span class="tag tag-caution">CD ${cdRemH.toFixed(1)}h</span>` : '';

    const posTag = hasPos
      ? (c.current_pos_qty > 0
          ? `<span class="tag tag-long">LONG $${Number(c.notional_usdt).toFixed(1)}</span>`
          : `<span class="tag tag-short">SHORT $${Number(c.notional_usdt).toFixed(1)}</span>`)
      : '<span class="tag">Кеш</span>';

    const f = c.factors || {};
    let facHtml = '';
    if(f.z_mom !== undefined){
      facHtml = `<div class="factor-strip mono">
        <span class="factor-pill">Mom ${Number(f.z_mom)>=0?'+':''}${Number(f.z_mom).toFixed(1)}</span>
        <span class="factor-pill">Car ${Number(f.z_carry)>=0?'+':''}${Number(f.z_carry).toFixed(1)}</span>
        <span class="factor-pill">BAB ${Number(f.z_bab)>=0?'+':''}${Number(f.z_bab).toFixed(1)}</span>
        <span class="factor-pill">Flw ${Number(f.z_flow)>=0?'+':''}${Number(f.z_flow).toFixed(1)}</span>
      </div>`;
    }

    const upnl = Number(c.unrealized_pnl || 0);
    const tw = Number(c.target_weight || 0);
    const sc = Number(c.alpha_score || 0);

    return `<article class="${cardCls}">
      <div>
        <div class="coin-hdr">
          <span class="coin-sym mono">${sym} ${sbBadge} ${cdBadge}</span>
          <span class="mono" style="font-size:12.5px;font-weight:600">$${c.price ? Number(c.price).toLocaleString(undefined,{maximumFractionDigits:4}) : 'N/A'}</span>
        </div>
        <div style="margin:5px 0">${posTag} <span style="font-size:11.5px;color:var(--muted)">${escapeHtml(c.phase_label || '')}</span></div>
        ${facHtml}
        <div class="coin-stats mono" style="margin-top:6px">
          <span>Ціль: <strong>${tw>=0?'+':''}${tw.toFixed(3)}x</strong></span>
          <span>uPnL: <strong class="${upnl>=0?'pos-val':'neg-val'}">${upnl>=0?'+':''}$${upnl.toFixed(2)}</strong></span>
          <span>Score: <strong>${sc>=0?'+':''}${sc.toFixed(3)}</strong></span>
          <span>Бета: <strong>${f.beta_btc !== undefined ? Number(f.beta_btc).toFixed(2) : 'N/A'}</strong></span>
        </div>
      </div>
      <div class="coin-ctrl-row">
        <select aria-label="Режим торгівлі ${sym}" onchange="updateCoinMode('${sym}', this.value)">
          <option value="1" ${c.mode===1?'selected':''}>AUTO (L+S)</option>
          <option value="2" ${c.mode===2?'selected':''}>LONG ONLY</option>
          <option value="3" ${c.mode===3?'selected':''}>SHORT ONLY</option>
          <option value="4" ${c.mode===4?'selected':''}>CORE ONLY</option>
          <option value="0" ${c.mode===0?'selected':''}>OFF (Вимк.)</option>
        </select>
        <input type="number" step="0.05" min="0.2" max="3.5" value="${Number(c.base_weight||1).toFixed(2)}"
               aria-label="Вага пріоритету ${sym}" onchange="updateCoinWeight('${sym}', this.value)">
      </div>
    </article>`;
  }).join('');
}

function switchChartMode(m){
  chartViewMode = m;
  const eqBtn = document.getElementById('tabEqMode');
  const arBtn = document.getElementById('tabArenaMode');
  eqBtn.className = 'seg-btn' + (m === 'equity' ? ' active' : '');
  arBtn.className = 'seg-btn' + (m === 'arena' ? ' active' : '');
  eqBtn.setAttribute('aria-pressed', m === 'equity' ? 'true' : 'false');
  arBtn.setAttribute('aria-pressed', m === 'arena' ? 'true' : 'false');
  renderMainChart();
}

/* Confirmed Controls */
function confirmCleanHistory(){
  openConfirmModal(
    'Архівування історії графіків',
    'Старі неактивні записи будуть перенесені у backups/, а відлік графіка почнеться з поточного балансу.',
    'Архівувати і скинути',
    false,
    async () => {
      try{
        const r = await apiFetch('/api/v1/control/reset-history', {method:'POST'});
        if(r && r.ok){ showToast('Історію архівовано, новий графік ініціалізовано.'); setTimeout(refreshAll, 1500); }
      }catch(e){ showToast('Не вдалося очистити історію графіка.', true); }
    }
  );
}

function confirmRestartServer(){
  openConfirmModal(
    'Перезапуск служби QuantCore',
    'Сервер збереже поточний стан на диск і перезапуститься через systemd (орієнтовно 3 секунди). Біржові STOP_MARKET залишаються активними.',
    'Перезапустити службу',
    true,
    async () => {
      try{
        await apiFetch('/api/v1/control/restart', {method:'POST'});
        showToast('Команду перезапуску прийнято (очікування 4с)...');
        setTimeout(refreshAll, 4500);
      }catch(e){ showToast('Помилка відправки команди рестарту.', true); }
    }
  );
}

function confirmPanicClose(){
  openConfirmModal(
    'Екстрене закриття всіх позицій у USDT',
    'Усі відкриті позиції по всіх парах буде негайно закрито за ринком у 100% USDT, а оркестратор стане на паузу.',
    'Ліквідувати позиції в кеш',
    true,
    async () => {
      try{
        await apiFetch('/api/v1/control/panic', {method:'POST'});
        showToast('Усі позиції закрито в USDT, торгівлю призупинено.', true);
        refreshAll();
      }catch(e){ showToast('Помилка аварійного закриття.', true); }
    }
  );
}

function confirmRollbackCartridge(){
  openConfirmModal(
    'Відкат картриджа моделі',
    'Повернути попередній збережений файл моделі (.joblib) без зупинки сервера?',
    'Виконати відкат',
    false,
    async () => {
      try{
        const r = await apiFetch('/api/v1/cartridge/rollback', {method:'POST'});
        if(r && r.ok){ showToast(`Активовано попередній картридж: ${r.active_cartridge}`); refreshAll(); }
      }catch(e){ showToast('Не вдалося виконати відкат картриджа.', true); }
    }
  );
}

async function updateCoinMode(sym, modeVal){
  try{
    const m = parseInt(modeVal, 10);
    await apiFetch('/api/v1/control/coin', {
      method:'POST', body: JSON.stringify({symbol: sym, mode: m, enabled: m !== 0})
    });
    showToast(`${sym}: режим торгівлі оновлено.`);
    loadState();
  }catch(e){ showToast(`Помилка оновлення ${sym}.`, true); }
}

async function updateCoinWeight(sym, wVal){
  try{
    await apiFetch('/api/v1/control/coin', {
      method:'POST', body: JSON.stringify({symbol: sym, base_weight: parseFloat(wVal)})
    });
    showToast(`${sym}: базову вагу встановлено на ${wVal}x.`);
    loadState();
  }catch(e){ showToast(`Помилка зміни ваги ${sym}.`, true); }
}

async function changeRiskProfile(){
  const prof = document.getElementById('riskSelect').value;
  const om = document.getElementById('orchModeSelect').value;
  try{
    const r = await apiFetch('/api/v1/control/risk', {
      method:'POST', body: JSON.stringify({risk_profile: prof, orchestrator_mode: om})
    });
    if(r && r.ok) showToast(`Профіль ризику змінено на ${prof}.`);
    else showToast(r?.detail || 'Відмова зміни профілю.', true);
  }catch(e){ showToast(`Помилка: ${e.message}`, true); }
  setTimeout(refreshAll, 1500);
}

async function runPreflight(){
  lastFocusedBeforeModal = document.activeElement;
  try{
    const d = await apiFetch('/api/v1/system/preflight');
    if(!d.ok || !d.preflight){ showToast('Діагностика Pre-Flight наразі недоступна.', true); return; }
    const p = d.preflight;
    const rows = [
      ['Режим середовища', p.demo_trading_mode ? 'DEMO / TESTNET' : 'LIVE PRODUCTION'],
      ['Віртуальна стеля капіталу', p.virtual_equity_cap > 0 ? `$${p.virtual_equity_cap}` : '100% балансу гаманця'],
      ['Двигун картриджа', `${String(p.cartridge_engine || '').toUpperCase()} (${p.symbols_count} пар, ${p.candle_timeframe})`],
      ['Зв\'язок із Binance / One-Way', `${p.exchange_reachable ? 'OK' : 'Немає ключів'} / ${p.one_way_mode_ok ? 'OK' : 'Перевірте режим'}`],
      ['Артефакт ML ранжера', p.ml_ranker_v5_present ? 'ml_ranker_v5 завантажено' : (p.ml_ranker_v3_present ? 'ml_ranker_v3 завантажено' : 'Лінійне ядро')],
      ['Баланс USDT / BNB / BFUSD', `$${p.usdt_wallet_balance} / ${p.bnb_fee_burn_balance} / $${p.bfusd_collateral_balance}`],
      ['Споживання RAM процесу', `${p.ram_rss_mb} MB`],
    ];
    document.getElementById('preflightList').innerHTML = rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`).join('');
    document.getElementById('preflightModal').classList.add('open');
  }catch(e){ showToast('Не вдалося виконати Pre-Flight діагностику.', true); }
}

function renderArena(rows){
  const tb = document.getElementById('arenaBody');
  if(!tb) return;
  if(!rows || !rows.length){
    tb.innerHTML = '<tr><td colspan="9" class="empty-cell">Shadow Arena ініціалізована. Результати з\'являться після закриття першої свічки.</td></tr>';
    return;
  }
  tb.innerHTML = rows.map(r => {
    const ret = Number(r.return_pct || 0);
    const rc = ret >= 0 ? 'pos-val' : 'neg-val';
    return `<tr class="mono">
      <td>#${r.rank}</td>
      <td><strong>${escapeHtml(r.bot_id)}</strong> <span style="color:var(--muted);font-size:11.5px">${escapeHtml(r.label)}</span></td>
      <td>$${Number(r.initial_equity||0).toLocaleString()}</td>
      <td><strong>$${Number(r.equity||0).toLocaleString(undefined,{minimumFractionDigits:2})}</strong></td>
      <td class="${rc}"><strong>${ret>=0?'+':''}${ret.toFixed(2)}%</strong></td>
      <td class="neg-val">${Number(r.max_dd_pct||0).toFixed(2)}%</td>
      <td>${Number(r.gross_lev||0).toFixed(2)}x / ${Number(r.net_lev||0)>=0?'+':''}${Number(r.net_lev||0).toFixed(2)}x</td>
      <td>${r.active_positions}</td>
      <td>${r.trades_count} ($${Number(r.fees_usd||0).toFixed(2)})</td>
    </tr>`;
  }).join('');
}

async function downloadV2Zip(){
  const tok = localStorage.getItem('qc_token') || '';
  showToast('Формування ZIP-архіву телеметрії...');
  try{
    const resp = await fetch('/api/v1/v2/export', {headers:{'X-Api-Key': tok}});
    if(!resp.ok){ showToast('Не вдалося сформувати ZIP-архів.', true); return; }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'quantcore_telemetry_bundle.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast('ZIP-архів телеметрії завантажено.');
  }catch(e){ showToast('Помилка завантаження ZIP-архіву.', true); }
}

async function refreshNews(){
  showToast('Оновлення RSS-стрічок та оцінки гео-шоку...');
  try{
    const d = await apiFetch('/api/v1/news?refresh=true');
    if(d.ok && d.news) renderNews(d.news);
    showToast('Стрічку новин оновлено.');
  }catch(e){ showToast('Не вдалося оновити RSS-стрічку.', true); }
}

function renderNews(news){
  if(!news) return;
  const s = Number(news.macro_sentiment || 0);
  const p = Number(news.geo_shock_prob || 0);
  const nv = document.getElementById('newsVal');
  nv.textContent = (s >= 0 ? '+' : '') + s.toFixed(2);
  nv.className = s > 0.1 ? 'pos-val' : (s < -0.1 ? 'neg-val' : '');
  document.getElementById('shockProbVal').textContent = `${Math.round(p * 100)}%`;
  document.getElementById('geoShockBadge').style.display = news.is_geo_shock ? 'inline-block' : 'none';

  const ul = document.getElementById('newsList');
  const hl = news.headlines || [];
  if(!hl.length){
    ul.innerHTML = '<li style="color:var(--muted)">Наразі заголовків немає. Натисніть «Оновити RSS» для примусового опитування джерел.</li>';
    return;
  }
  ul.innerHTML = hl.slice(0, 6).map(h => `<li>${escapeHtml(h)}</li>`).join('');
}

async function triggerWakeup(){
  try{
    await apiFetch('/api/v1/control/wakeup', {method:'POST'});
    showToast('Позачерговий перерахунок портфеля запущено.');
    setTimeout(refreshAll, 2500);
  }catch(e){ showToast('Не вдалося запустити перерахунок.', true); }
}

async function togglePause(){
  try{
    await apiFetch('/api/v1/control/pause', {
      method:'POST', body: JSON.stringify({paused: !isPausedState})
    });
    showToast(!isPausedState ? 'Торгівлю поставлено на паузу.' : 'Штатну торгівлю відновлено.');
    loadState();
  }catch(e){ showToast('Помилка перемикання паузи.', true); }
}

async function uploadCartridge(){
  const fInput = document.getElementById('joblibFile');
  if(!fInput.files.length){ showToast('Спочатку оберіть локальний файл .joblib.', true); return; }
  const fd = new FormData();
  fd.append('file', fInput.files[0]);
  showToast('Виконується гаряча заміна моделі...');
  try{
    const tok = localStorage.getItem('qc_token') || '';
    const resp = await fetch('/api/v1/cartridge/upload', {
      method:'POST', headers:{'X-Api-Key': tok}, body: fd
    });
    const d = await resp.json();
    if(resp.ok && d.ok){
      showToast(`Активовано картридж: ${d.active_cartridge}`);
      fInput.value = '';
      refreshAll();
    } else {
      showToast(d.detail || 'Файл моделі відхилено сервером.', true);
    }
  }catch(e){ showToast('Помилка завантаження файлу моделі.', true); }
}

async function loadState(){
  try{
    const d = await apiFetch('/api/v1/state');
    if(!d.ok) return;
    const eng = d.engine || {};
    const res = d.resources || {};
    const t = eng.telemetry || {};
    const v2 = d.v2_analytics || {};
    const hb = d.heartbeat || {};
    const lim = d.risk_limits || {};

    isPausedState = Boolean(eng.is_paused);
    const stChip = document.getElementById('statusChip');
    stChip.className = 'status-chip' + (isPausedState ? ' paused' : '');
    document.getElementById('statusText').textContent = isPausedState ? 'ПАУЗА' : 'АКТИВНИЙ';
    document.getElementById('pauseBtn').textContent = isPausedState ? 'Відновити' : 'Пауза';

    const vCap = Number(d.virtual_equity_cap || 0);
    const envEl = document.getElementById('envBadge');
    envEl.className = 'status-chip mono ' + (d.demo_trading ? 'chip-caution' : 'chip-short');
    envEl.textContent = d.demo_trading ? (vCap > 0 ? `DEMO $${vCap.toFixed(0)}` : 'DEMO') : 'LIVE REAL';

    const engCode = String(d.cartridge_engine || 'v6').toUpperCase();
    document.getElementById('cartridgeBadge').textContent = engCode;
    document.getElementById('tfBadge').textContent = d.candle_timeframe || '1h';
    document.getElementById('ramBadge').textContent = res.ram_rss_mb ? `${res.ram_rss_mb} MB` : 'N/A';
    document.getElementById('diskBadge').textContent = res.storage_used_mb ? `${res.storage_used_mb} MB` : 'N/A';
    document.getElementById('candleBadge').textContent = String(t.timestamp || eng.last_candle_ts || 'N/A').slice(0, 16);
    document.getElementById('uptimeBadge').textContent = fmtDuration(eng.uptime_sec);
    document.getElementById('hbBadge').textContent = hb.present && hb.age_sec !== null ? `${fmtDuration(hb.age_sec)} (${hb.status || 'ok'})` : 'N/A';
    document.getElementById('calcLatencyBadge').textContent = t.calc_ms !== undefined ? `calc: ${Number(t.calc_ms).toFixed(0)} ms` : 'calc: N/A';

    if(eng.risk_profile) document.getElementById('riskSelect').value = eng.risk_profile;
    if(eng.orchestrator_mode) document.getElementById('orchModeSelect').value = eng.orchestrator_mode;

    const totEq = Number(t.total_equity || 0);
    if(totEq > 0){
      document.getElementById('kpiEquity').textContent = `$${totEq.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    }
    if(t.wallet_balance !== undefined){
      const up = Number(t.unrealized_pnl || 0);
      document.getElementById('kpiWalletUpnl').textContent = `$${Number(t.wallet_balance).toFixed(2)} (${up>=0?'+':''}$${up.toFixed(2)})`;
    }

    const ag = Number(t.a_gross || 0), bg = Number(t.b_gross || 0), sg = Number(t.s_gross ?? t.c_gross ?? 0), dg = Number(t.d_gross || 0);
    const grossL = Number(t.gross_leverage ?? (ag + bg + sg + dg));
    const netL = Number(t.net_leverage || 0);
    document.getElementById('kpiLev').textContent = `${grossL.toFixed(2)}x / ${netL>=0?'+':''}${netL.toFixed(2)}x`;
    document.getElementById('kpiTargetBeta').textContent = (t.committed_beta !== null && t.committed_beta !== undefined)
      ? `${Number(t.committed_beta)>=0?'+':''}${Number(t.committed_beta).toFixed(2)}`
      : 'N/A (V6.1)';

    const brPct = Number(t.market_breadth || 0) * 100;
    const btPct = Number(t.btc_trend || 0) * 100;
    const regEl = document.getElementById('regimeBadge');
    const regLbl = t.regime_label || ((btPct > 2.0 && brPct >= 52) ? 'BULL_TREND' : ((btPct < -2.5 && brPct <= 35) ? 'BEAR_TREND' : 'CHOP_NEUTRAL'));
    if(String(regLbl).includes('BULL')){
      regEl.className = 'status-chip chip-long mono'; regEl.textContent = 'BULL TREND';
    } else if(String(regLbl).includes('BEAR')){
      regEl.className = 'status-chip chip-short mono'; regEl.textContent = 'BEAR TREND';
    } else {
      regEl.className = 'status-chip mono'; regEl.textContent = 'CHOP NEUTRAL';
    }

    const v3Tier = t.active_v3_tier || (t.tier ? `TIER ${t.tier}` : 'N/A');
    document.getElementById('tierBadge').textContent = v3Tier;

    if(v2 && v2.ok){
      const mkPct = Number(v2.maker_fill_pct || 0).toFixed(1);
      const slp = Number(v2.avg_slippage_arrival_bps || 0);
      document.getElementById('kpiMakerSlip').textContent = `${mkPct}% / ${slp>=0?'+':''}${slp.toFixed(2)} bps`;
      const fnd = Number(v2.net_funding_income_usdt || 0);
      document.getElementById('kpiSpreadFund').textContent = `${Number(v2.avg_spread_bps||0).toFixed(2)} bps / ${fnd>=0?'+$':'-$'}${Math.abs(fnd).toFixed(3)}`;
    }

    /* Pipeline Rail & Risk Armor */
    const coins = eng.coins || [];
    const skCounts = t.skipped_counts || {};
    const skTot = Object.values(skCounts).reduce((a, b) => a + Number(b || 0), 0);
    const cdMap = t.stop_cooldowns || {};
    const activeCds = Object.values(cdMap).filter(tsU => Number(tsU) > Date.now()).length;

    document.getElementById('leaderSummary').textContent = `Флагман книги: ${t.top_leader || 'N/A'}`;
    document.getElementById('pipeUniverse').textContent = `${coins.length} пар активні`;
    document.getElementById('pipeBreadth').textContent = `Breadth: ${brPct.toFixed(1)}% | BTC EMA200: ${btPct>=0?'+':''}${btPct.toFixed(2)}%`;
    document.getElementById('pipeRegimeTier').textContent = `${regEl.textContent} / ${v3Tier}`;
    document.getElementById('pipeDispersion').textContent = `Дисперсія альфи: ${t.cs_dispersion !== undefined ? Number(t.cs_dispersion).toFixed(3) : 'N/A'}`;
    document.getElementById('pipePodsGross').textContent = `Pod B: ${bg.toFixed(2)}x | Загалом: ${grossL.toFixed(2)}x`;
    document.getElementById('pipePodsSub').textContent = `RegBeta/A: ${ag.toFixed(2)}x | Pod S/C: ${sg.toFixed(2)}x`;
    document.getElementById('pipeSkippedTotal').textContent = `${skTot} сигналів відсіяно`;
    document.getElementById('pipeSkippedBreak').textContent = `spread: ${skCounts.pre_spread_veto||0} | minNot: ${(skCounts.min_notional||0)+(skCounts.lot_filter||0)} | deadzone: ${skCounts.deadzone||0}`;
    const openCnt = coins.filter(c => Math.abs(Number(c.current_pos_qty || 0)) > 0).length;
    document.getElementById('pipeLivePos').textContent = `${openCnt} відкритих на біржі`;
    document.getElementById('pipeCooldowns').textContent = `Активні 48h стоп-кулдауни: ${activeCds}`;

    /* Risk Armor Bars */
    const dailyLim = Number(lim.daily_dd_limit_pct || 5.0);
    const totalLim = Number(lim.max_total_dd_pct || 20.0);
    const grossCap = Number(lim.hard_gross_cap || 2.25);
    const imbLim = Number(lim.neutrality_imbalance_limit || 0.05);

    document.getElementById('limDailyLbl').textContent = `${dailyLim.toFixed(1)}%`;
    document.getElementById('limTotalLbl').textContent = `${totalLim.toFixed(1)}%`;
    document.getElementById('limGrossLbl').textContent = `${grossCap.toFixed(2)}x`;

    const dayStart = Number(eng.daily_starting_equity || t.daily_starting_equity || totEq);
    const peakEq = Number(eng.peak_equity || t.peak_equity || totEq);
    const curDailyDd = (dayStart > 0 && totEq > 0) ? Math.max(0, (dayStart - totEq) / dayStart * 100) : 0;
    const curPeakDd = (peakEq > 0 && totEq > 0) ? Math.max(0, (peakEq - totEq) / peakEq * 100) : 0;
    const realizedNet = coins.reduce((acc, c) => acc + Number(c.realized_weight || 0), 0);
    const targetNet = coins.reduce((acc, c) => acc + Number(c.target_weight || 0), 0);
    const curImb = Math.abs(realizedNet - targetNet);

    function setMeter(valId, barId, valStr, ratio){
      document.getElementById(valId).textContent = valStr;
      const bar = document.getElementById(barId);
      const pct = Math.max(0, Math.min(100, ratio * 100));
      bar.style.width = `${pct.toFixed(1)}%`;
      bar.className = 'meter-bar' + (ratio >= 0.85 ? ' crit' : (ratio >= 0.60 ? ' warn' : ''));
    }
    setMeter('valDailyDd', 'barDailyDd', `-${curDailyDd.toFixed(2)}%`, curDailyDd / Math.max(dailyLim, 0.1));
    setMeter('valPeakDd', 'barPeakDd', `-${curPeakDd.toFixed(2)}%`, curPeakDd / Math.max(totalLim, 0.1));
    setMeter('valGrossCap', 'barGrossCap', `${grossL.toFixed(2)}x`, grossL / Math.max(grossCap, 0.1));
    setMeter('valImbalance', 'barImbalance', `${curImb.toFixed(3)}x`, curImb / Math.max(imbLim, 0.01));

    const vcEl = document.getElementById('vCapBadge');
    if(vcEl) vcEl.textContent = vCap > 0 ? `Віртуальний ліміт демо-рахунку: $${vCap.toFixed(0)} USDT` : 'Режим балансу: 100% біржового гаманця';
    if(d.shadow_arena) renderArena(d.shadow_arena);
    if(d.news) renderNews(d.news);

    const filterEl = document.getElementById('tradeSymFilter');
    if(filterEl && coins.length > 0){
      const curVal = filterEl.value;
      const coinSyms = coins.map(c => c.symbol).filter(Boolean);
      const existingOpts = Array.from(filterEl.options).map(o => o.value);
      if(coinSyms.some(s => !existingOpts.includes(s)) || existingOpts.length <= 1){
        filterEl.innerHTML = '<option value="">Усі валюти</option>' + coinSyms.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
        filterEl.value = curVal;
      }
    }

    renderActivePositionsTable(coins);
    renderCoinsMatrix(coins);
    renderAllocationVector(coins);
    document.getElementById('footerSyncStamp').textContent = `Остання синхронізація UI: ${new Date().toISOString().slice(11, 19)} UTC`;
  }catch(e){
    if(e.message !== 'Unauthorized'){
      document.getElementById('statusChip').className = 'status-chip offline';
      document.getElementById('statusText').textContent = 'ПОМИЛКА ЗВ\'ЯЗКУ';
      document.getElementById('globalErrorText').textContent = `Не вдалося отримати /api/v1/state (${e.message}). Перевірте доступність сервера.`;
      document.getElementById('globalErrorBanner').style.display = 'flex';
    }
  }
}

async function loadCharts(days){
  if(days){
    currentChartDays = days;
    [1,7,30,365].forEach(d => {
      const b = document.getElementById('rng-' + d);
      if(b) b.className = 'seg-btn' + (d === days ? ' active' : '');
    });
  }
  try{
    const d = await apiFetch('/api/v1/equity?days=' + currentChartDays);
    if(!d.ok || !d.kpis){
      renderMainChart();
      return;
    }
    lastChartPayload = d;
    const k = d.kpis;
    if(k.latest_equity !== undefined){
      document.getElementById('kpiEquity').textContent = `$${Number(k.latest_equity).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
      const pnl = Number(k.total_pnl_pct || 0);
      const pnlEl = document.getElementById('kpiPnlPct');
      pnlEl.textContent = `${pnl>=0?'+':''}${pnl.toFixed(2)}% за вибране вікно (Win rate: ${Number(k.win_rate_pct||0).toFixed(0)}%)`;
      pnlEl.className = 'focal-delta mono ' + (pnl >= 0 ? 'pos-val' : 'neg-val');

      const alp = Number(k.alpha_vs_btc_pct || 0);
      const alpEl = document.getElementById('kpiAlpha');
      alpEl.textContent = `${alp>=0?'+':''}${alp.toFixed(2)}%`;
      alpEl.className = alp >= 0 ? 'pos-val' : 'warn-val';

      const bbh = Number(k.btc_bh_pct || 0);
      document.getElementById('kpiBtcBh').textContent = `${bbh>=0?'+':''}${bbh.toFixed(2)}%`;
      document.getElementById('kpiSharpeCalmar').textContent = `${Number(k.sharpe_ratio||0).toFixed(2)} / ${Number(k.calmar_ratio||0).toFixed(2)}`;
      document.getElementById('kpiMdd').textContent = `${Number(k.max_drawdown_pct||0).toFixed(2)}%`;
      document.getElementById('kpiFees').textContent = `$${Number(k.total_fees_usdt||0).toFixed(2)} / ${k.total_ops||0}`;
    }
    renderMainChart();
  }catch(e){
    const ph = document.getElementById('equityPlaceholder');
    if(ph && e.message !== 'Unauthorized'){
      ph.textContent = 'Помилка завантаження графіка капіталу. Натисніть «Повторити запит» вище.';
      ph.style.display = 'flex';
    }
  }
}

async function loadV2Telemetry(){
  const tb = document.getElementById('v2ExecBody');
  try{
    const d = await apiFetch('/api/v1/v2/telemetry?limit=25');
    if(!d.ok) return;
    const rows = d.executions || [];
    if(!rows.length){
      tb.innerHTML = '<tr><td colspan="7" class="empty-cell">Нових записів виконання ордерів поки немає.</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(r => {
      const sCls = r.side === 'BUY' ? 'pos-val' : 'neg-val';
      const mkLbl = r.is_maker ? 'MAKER' : (r.maker_fallback_used ? 'IOC/TAKER' : 'TAKER');
      const slp = Number(r.slippage_arrival_bps || 0);
      return `<tr class="mono">
        <td>${escapeHtml(String(r.ts || '').slice(5, 16))}</td>
        <td><strong>${escapeHtml(r.symbol)}</strong> <span class="${sCls}">${escapeHtml(r.side)}</span></td>
        <td>${escapeHtml(String(r.sleeve_book || '').replace('SLEEVE_', ''))}</td>
        <td>${mkLbl}</td>
        <td class="${slp <= 3.0 ? 'pos-val' : 'warn-val'}">${slp>=0?'+':''}${slp.toFixed(1)}</td>
        <td>${Number(r.spread_bps||0).toFixed(1)}</td>
        <td>${escapeHtml(r.order_status)}</td>
      </tr>`;
    }).join('');
  }catch(e){
    if(e.message !== 'Unauthorized') tb.innerHTML = '<tr><td colspan="7" class="empty-cell">Не вдалося завантажити таблицю виконання ордерів.</td></tr>';
  }
}

async function loadTrades(){
  const tb = document.getElementById('tradesBody');
  try{
    const sym = document.getElementById('tradeSymFilter').value;
    const d = await apiFetch('/api/v1/trades?limit=35&symbol=' + encodeURIComponent(sym));
    const rows = d.trades || [];
    if(!rows.length){
      tb.innerHTML = '<tr><td colspan="5" class="empty-cell">У журналі немає виконаних угод за цим фільтром.</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(t => {
      const sCls = t.side === 'BUY' ? 'pos-val' : 'neg-val';
      const pnl = Number(t.net_pnl || 0);
      const pCls = pnl >= 0 ? 'pos-val' : 'neg-val';
      return `<tr class="mono">
        <td>${escapeHtml(String(t.time || '').slice(5, 16))}</td>
        <td><strong>${escapeHtml(t.symbol)}</strong></td>
        <td class="${sCls}"><strong>${escapeHtml(t.side)} ${t.amount}</strong></td>
        <td>$${Number(t.price||0).toLocaleString()}</td>
        <td class="${pCls}"><strong>${pnl>=0?'+':''}$${pnl.toFixed(2)}</strong></td>
      </tr>`;
    }).join('');
  }catch(e){
    if(e.message !== 'Unauthorized') tb.innerHTML = '<tr><td colspan="5" class="empty-cell">Помилка читання журналу угод.</td></tr>';
  }
}

function renderFilteredLogs(){
  const box = document.getElementById('logBox');
  const q = (document.getElementById('logSearch').value || '').trim().toLowerCase();
  if(!cachedLogs.length){
    box.textContent = 'Файл логу порожній або ще не створений.';
    return;
  }
  const lines = q ? cachedLogs.filter(ln => ln.toLowerCase().includes(q)) : cachedLogs;
  box.textContent = lines.length ? lines.join('\n') : 'Жоден рядок логу не відповідає введеному фільтру.';
  box.scrollTop = box.scrollHeight;
}

async function loadLogs(){
  const box = document.getElementById('logBox');
  try{
    const d = await apiFetch('/api/v1/logs?lines=50');
    if(d.ok){
      cachedLogs = d.lines || [];
      renderFilteredLogs();
    }
  }catch(e){
    if(e.message !== 'Unauthorized') box.textContent = 'Не вдалося прочитати останні рядки логу сервера.';
  }
}

function refreshAll(){
  loadState();
  loadCharts();
  loadV2Telemetry();
  loadTrades();
  loadLogs();
}

refreshAll();
setInterval(() => { if(!document.hidden) loadState(); }, 10000);
setInterval(() => { if(!document.hidden) loadCharts(); }, 30000);
setInterval(() => { if(!document.hidden) loadV2Telemetry(); }, 20000);
setInterval(() => { if(!document.hidden) loadLogs(); }, 20000);
document.addEventListener('visibilitychange', () => {
  if(!document.hidden){
    tickCandleCountdown();
    refreshAll();
  }
});
</script>
</body>
</html>
"""
