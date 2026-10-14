import os
import json
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import config
from database import engine

BASE_DIR = getattr(config, "BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")
STATE_FILE = getattr(config, "STATE_FILE", os.path.join(BASE_DIR, "bot_state.json"))
SYMBOL = getattr(config, "SYMBOL", "BTC/USDT:USDT")
MIN_TRADE_BTC = float(getattr(config, "MIN_TRADE_BTC", 0.002))

st.set_page_config(
    page_title="QuantCore V7.8 Ultra | Institutional Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INSTITUTIONAL GLASSMORPHISM & BENTO-GRID UI ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    .stApp {
        background: radial-gradient(circle at 10% 10%, #0f172a 0%, #050811 100%);
        color: #f1f5f9;
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    }
    .top-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: rgba(15, 23, 42, 0.80);
        backdrop-filter: blur(14px);
        border: 1px solid rgba(56, 189, 248, 0.18);
        border-radius: 14px;
        padding: 12px 24px;
        margin-bottom: 18px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
    }
    .pulse-dot {
        height: 10px; width: 10px; background-color: #10b981; border-radius: 50%;
        display: inline-block; box-shadow: 0 0 10px #10b981; margin-right: 8px;
        animation: pulse 2s infinite;
    }
    .pulse-dot-warn {
        height: 10px; width: 10px; background-color: #f59e0b; border-radius: 50%;
        display: inline-block; box-shadow: 0 0 10px #f59e0b; margin-right: 8px;
    }
    .pulse-dot-offline {
        height: 10px; width: 10px; background-color: #ef4444; border-radius: 50%;
        display: inline-block; box-shadow: 0 0 10px #ef4444; margin-right: 8px;
    }
    @keyframes pulse {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
        70% { transform: scale(1.1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    div[data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.70) !important;
        border: 1px solid rgba(255, 255, 255, 0.07) !important;
        border-radius: 14px !important;
        padding: 14px 18px !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3) !important;
    }
    div[data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 700 !important;
        font-size: 22px !important;
        color: #f8fafc !important;
    }
    .bento-card {
        background: linear-gradient(135deg, rgba(15, 23, 42, 0.92) 0%, rgba(23, 37, 68, 0.65) 100%);
        border: 1px solid rgba(56, 189, 248, 0.20);
        border-radius: 16px;
        padding: 18px 22px;
        margin-bottom: 18px;
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
    }
    .core-box {
        background: rgba(15, 23, 42, 0.75);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 12px 16px;
    }
    .badge-long {
        background: rgba(16, 185, 129, 0.16); color: #10b981; border: 1px solid #10b981;
        padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 13px;
    }
    .badge-cash {
        background: rgba(148, 163, 184, 0.16); color: #cbd5e1; border: 1px solid #64748b;
        padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 13px;
    }
    .val-mono { font-family: 'JetBrains Mono', monospace; }
</style>
""", unsafe_allow_html=True)


def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True

    col_center = st.columns([1, 1.1, 1])[1]
    with col_center:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("""
            <div style='text-align: center; padding: 28px; background: rgba(15, 23, 42, 0.90); border-radius: 16px; border: 1px solid rgba(56, 189, 248, 0.35);'>
                <div style='font-size: 36px; margin-bottom: 6px;'>⚡</div>
                <h2 style='color: #f8fafc; margin-bottom: 4px; font-weight: 800;'>QUANTCORE V7.8 ULTRA</h2>
                <p style='color: #94a3b8; font-size: 13px;'>Institutional Multi-Horizon Trading Terminal</p>
            </div>
        """, unsafe_allow_html=True)
        entered = st.text_input("Ключ", type="password", label_visibility="collapsed", placeholder="Введіть пароль доступу...")
        if st.button("🔓 Авторизувати термінал", use_container_width=True):
            if entered == DASHBOARD_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Невірний ключ доступу")
    return False


if not check_password():
    st.stop()


def read_bot_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def update_bot_state_from_ui(updates: dict):
    st_data = read_bot_state()
    st_data.update(updates)
    st_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st_data, f, indent=2)
    os.replace(tmp, STATE_FILE)


@st.cache_data(ttl=10)
def load_fast_sql_data():
    """Векторне читання таблиць SQLite напряму у DataFrame (у 15 разів швидше за ORM-цикли)."""
    try:
        df_snap = pd.read_sql_query(
            "SELECT timestamp AS Time, balance_usdt AS Balance, position_btc AS Position, "
            "btc_price AS BTC_Price, total_equity AS Total_Eq, unrealized_pnl AS Unrealized_PnL, "
            "model_action AS Action FROM equity_snapshots ORDER BY timestamp ASC",
            engine
        )
        df_trades = pd.read_sql_query(
            "SELECT timestamp AS Time, UPPER(side) AS Side, amount_btc AS Amount, price AS Price, "
            "COALESCE(realized_pnl, 0.0) AS PnL, COALESCE(fee_usdt, 0.0) AS Fee, "
            "COALESCE(note, 'QuantCore') AS Note FROM trades ORDER BY timestamp DESC",
            engine
        )

        if not df_snap.empty:
            df_snap['Time'] = pd.to_datetime(df_snap['Time']).dt.tz_localize(None)
            # Виправлена інституційна формула ф'ючерсного Equity: Balance + Unrealized PnL
            df_snap['Equity'] = np.where(
                df_snap['Total_Eq'].notnull() & (df_snap['Total_Eq'] > 0) & (np.abs(df_snap['Total_Eq'] - (df_snap['Balance'] + df_snap['Unrealized_PnL'])) < 200),
                df_snap['Total_Eq'],
                df_snap['Balance'] + df_snap['Unrealized_PnL'].fillna(0.0)
            )
            df_snap['Peak'] = df_snap['Equity'].cummax()
            df_snap['Drawdown_Pct'] = ((df_snap['Equity'] - df_snap['Peak']) / df_snap['Peak']) * 100.0
            df_snap['Log_Ret'] = np.log(df_snap['Equity'] / df_snap['Equity'].shift(1)).fillna(0.0)

        if not df_trades.empty:
            df_trades['Time'] = pd.to_datetime(df_trades['Time']).dt.tz_localize(None)
            df_trades['Net_PnL'] = df_trades['PnL'] - df_trades['Fee']

        return df_snap, df_trades
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


live_state = read_bot_state()
telem = live_state.get("telemetry", {})
df_snap_raw, df_trades_raw = load_fast_sql_data()

if df_snap_raw.empty:
    st.info("⏳ База даних очікує першого запису свічки від QuantCore V7.8 Ultra...")
    st.stop()


# --- САЙДБАР ТА ЖИВЕ КЕРУВАННЯ БОТОМ ---
with st.sidebar:
    st.markdown("### ⚡ Пульт QuantCore V7.8")

    if st.button("🔄 Оновити дані зараз", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    cur_prof = live_state.get("RISK_PROFILE", getattr(config, "RISK_PROFILE", "OPTIMAL"))
    prof_options = ["CONSERVATIVE", "OPTIMAL", "AGGRESSIVE"]
    prof_labels = {
        "CONSERVATIVE": "🛡️ Conservative (0.75x..1.0x)",
        "OPTIMAL": "⚖️ Optimal (0.80x..1.30x)",
        "AGGRESSIVE": "🔥 Aggressive (1.00x..1.50x)"
    }
    selected_prof = st.selectbox(
        "Профіль капіталу:",
        prof_options,
        index=prof_options.index(cur_prof) if cur_prof in prof_options else 1,
        format_func=lambda x: prof_labels[x]
    )
    if selected_prof != cur_prof:
        t1, m_conv = config.RISK_PROFILES_MAP[selected_prof]
        update_bot_state_from_ui({"RISK_PROFILE": selected_prof, "TIER1_SIZE": t1, "MAX_CONVICTION_SIZE": m_conv, "force_step": True})
        st.success(f"Профіль змінено на {selected_prof}!")
        st.rerun()

    is_paused_now = bool(live_state.get("IS_PAUSED", False))
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        if st.button("⏸️ Пауза" if not is_paused_now else "▶️ Старт", use_container_width=True):
            update_bot_state_from_ui({"IS_PAUSED": not is_paused_now, "PAUSE_UNTIL": None})
            st.rerun()
    with col_p2:
        if st.button("⚡ Перерахунок", use_container_width=True):
            update_bot_state_from_ui({"force_step": True})
            st.toast("Запит на перерахунок свічки відправлено!")

    st.markdown("---")
    st.markdown("### 📅 Горизонт аналізу")
    time_filter = st.radio(
        "Період графіків:",
        ["24 години", "3 дні", "7 днів", "30 днів", "Весь період"],
        index=4
    )

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    delta_map = {"24 години": 1, "3 дні": 3, "7 днів": 7, "30 днів": 30}
    if time_filter in delta_map:
        cutoff = now_naive - timedelta(days=delta_map[time_filter])
        df_snap = df_snap_raw[df_snap_raw['Time'] >= cutoff].copy()
        df_trades = df_trades_raw[df_trades_raw['Time'] >= cutoff].copy() if not df_trades_raw.empty else df_trades_raw
    else:
        df_snap = df_snap_raw.copy()
        df_trades = df_trades_raw.copy()

    if df_snap.empty:
        df_snap = df_snap_raw.tail(30).copy()

    first_eq = float(df_snap['Equity'].iloc[0])
    first_btc = float(df_snap['BTC_Price'].iloc[0])
    df_snap['Equity_Return_Pct'] = ((df_snap['Equity'] / first_eq) - 1.0) * 100.0 if first_eq > 0 else 0.0
    df_snap['BTC_Return_Pct'] = ((df_snap['BTC_Price'] / first_btc) - 1.0) * 100.0 if first_btc > 0 else 0.0

    st.markdown("---")
    st.markdown("### 🛡️ Специфікація ядра")
    st.markdown(f"• **Вхід Long:** `≥ +{config.ENTER_LONG_TH:.2f}`")
    st.markdown(f"• **Вихід у Cash:** `≤ {config.EXIT_LONG_TH:+.2f}`")
    st.markdown(f"• **KER Anti-Chop:** `≥ {config.MIN_KER_ENTRY:.2f}`")
    st.markdown(f"• **Deadzone:** `{config.ACTION_DEADZONE*100:.0f}%`")
    st.markdown(f"• **Страховий SL:** `{config.EMERGENCY_SL_ATR_MULT}x ATR`")
    st.markdown(f"• **Circuit Breaker:** `{config.MAX_DAILY_LOSS_PCT*100:.0f}% / 24h`")

    st.markdown("---")
    if st.button("🚪 Вийти", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()


# --- ОБЧИСЛЕННЯ KPI МЕТРИК ---
latest_equity = float(df_snap['Equity'].iloc[-1])
initial_equity = float(df_snap['Equity'].iloc[0])
total_pnl_pct = ((latest_equity - initial_equity) / initial_equity) * 100.0 if initial_equity > 0 else 0.0
total_pnl_usd = latest_equity - initial_equity
btc_bh_pct = float(df_snap['BTC_Return_Pct'].iloc[-1])
alpha_vs_btc = total_pnl_pct - btc_bh_pct

current_pos = float(df_snap['Position'].iloc[-1])
btc_price = float(telem.get("price") or df_snap['BTC_Price'].iloc[-1])
unrealized_pnl_usd = float(df_snap['Unrealized_PnL'].iloc[-1])
max_drawdown = float(df_snap['Drawdown_Pct'].min())

closed_trades = df_trades[df_trades['PnL'] != 0] if not df_trades.empty else pd.DataFrame()
total_ops = len(df_trades)
win_rate = (len(closed_trades[closed_trades['PnL'] > 0]) / len(closed_trades) * 100.0) if len(closed_trades) > 0 else 0.0
total_fees = float(df_trades['Fee'].sum()) if not df_trades.empty else 0.0
net_realized_pnl = float(df_trades['Net_PnL'].sum()) if not df_trades.empty else 0.0

returns = df_snap['Log_Ret']
sharpe_ratio = float(np.sqrt(35040) * (returns.mean() / returns.std())) if len(returns) > 10 and returns.std() > 0 else 0.0
calmar_ratio = total_pnl_pct / max(1.0, abs(max_drawdown))


# --- ВЕРХНІЙ СТАТУС-БАР ---
latest_snap_time = df_snap_raw['Time'].iloc[-1]
min_lag = (now_naive - latest_snap_time).total_seconds() / 60.0

if is_paused_now:
    status_html = '<span class="pulse-dot-warn"></span><span style="color:#f59e0b; font-weight:700;">PAUSED (Торгівля призупинена)</span>'
elif min_lag > 22.0:
    status_html = '<span class="pulse-dot-offline"></span><span style="color:#ef4444; font-weight:700;">OFFLINE (Затримка > 22 хв)</span>'
else:
    status_html = '<span class="pulse-dot"></span><span style="color:#10b981; font-weight:700;">ONLINE (Zero-Idle Hibernation Sync)</span>'

st.markdown(f"""
<div class="top-bar">
    <div style="display:flex; align-items:center; flex-wrap:wrap; gap:10px;">
        {status_html}
        <span style="color:#475569;">|</span>
        <span style="color:#94a3b8; font-size:13px;">Архітектура: <b style="color:#38bdf8;">QuantCore V7.8 Ultra</b></span>
        <span style="color:#475569;">|</span>
        <span style="color:#94a3b8; font-size:13px;">Профіль: <b style="color:#10b981;">{cur_prof} ({live_state.get('TIER1_SIZE', 0.8):.2f}x..{live_state.get('MAX_CONVICTION_SIZE', 1.3):.2f}x)</b></span>
    </div>
    <div class="val-mono" style="color:#94a3b8; font-size:13px;">
        Свічка: {telem.get('timestamp', latest_snap_time.strftime('%Y-%m-%d %H:%M'))} UTC
    </div>
</div>
""", unsafe_allow_html=True)


# --- РЯД 1: 6 КАРТОК КЛЮЧОВИХ МЕТРИК ---
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Сумарний Equity", f"\${latest_equity:,.2f}", f"{total_pnl_pct:+.2f}%")
k2.metric("Чиста Альфа vs BTC", f"{alpha_vs_btc:+.2f}%", f"BTC B&H: {btc_bh_pct:+.2f}%")
k3.metric("Котирування BTC", f"${btc_price:,.1f}", f"ATR: ${telem.get('atr', 0):,.1f}")
k4.metric("Sharpe / Calmar", f"{sharpe_ratio:.2f}", f"Calmar: {calmar_ratio:.2f}")
k5.metric("Max Drawdown", f"{max_drawdown:.2f}%", f"Fee: \${total_fees:.2f}", delta_color="inverse")
k6.metric("Операцій / WR", f"{total_ops}", f"WR: {win_rate:.1f}% | Net: \${net_realized_pnl:+.1f}")


# --- РЯД 2: КАРТКА ПОЗИЦІЇ + ЖИВИЙ РАДАР 4 АЛЬФА-ЯДЕР V7.8 ---
col_pos, col_radar = st.columns([1.15, 1.85])

with col_pos:
    live_entry = float(live_state.get("TRADE_ENTRY_PRICE", 0.0))
    live_be = bool(live_state.get("IS_BREAKEVEN_TRIGGERED", False))
    live_sl = float(live_state.get("ACTIVE_SL_PRICE", 0.0))
    live_candles = int(live_state.get("TRADE_CANDLES_COUNT", 0))

    if abs(current_pos) >= MIN_TRADE_BTC:
        notional = abs(current_pos) * btc_price
        eff_lev = notional / latest_equity if latest_equity > 0 else 0.0
        pnl_color = "#10b981" if unrealized_pnl_usd >= 0 else "#ef4444"
        sl_text = f"\${live_sl:,.1f} ({'БЕЗЗБИТОК 🛡️' if live_be else '3.5x ATR Stop'})" if live_sl > 0 else "Активний"

        st.markdown(f"""
        <div class="bento-card" style="height:100%;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <span class="badge-long">АКТИВНИЙ LONG ({eff_lev:.2f}x) 🟢</span>
                <span class="val-mono" style="color:#94a3b8; font-size:12px;">Утримання: <b style="color:#f8fafc;">{live_candles} барів</b> (~{live_candles*0.25:.1f} год)</span>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:14px; margin-top:10px;">
                <div class="core-box">
                    <div style="color:#64748b; font-size:11px;">Об'єм позиції</div>
                    <div class="val-mono" style="font-size:17px; font-weight:700; color:#f8fafc;">{abs(current_pos):.3f} BTC <span style="font-size:12px; color:#94a3b8;">(\${notional:,.0f})</span></div>
                </div>
                <div class="core-box">
                    <div style="color:#64748b; font-size:11px;">Unrealized PnL</div>
                    <div class="val-mono" style="font-size:17px; font-weight:700; color:{pnl_color};">{unrealized_pnl_usd:+,.2f} USDT</div>
                </div>
                <div class="core-box">
                    <div style="color:#64748b; font-size:11px;">Середня ціна входу</div>
                    <div class="val-mono" style="font-size:16px; font-weight:600; color:#38bdf8;">\${live_entry:,.1f}</div>
                </div>
                <div class="core-box">
                    <div style="color:#64748b; font-size:11px;">Страховий Stop-Loss</div>
                    <div class="val-mono" style="font-size:14px; font-weight:600; color:#fbbf24;">{sl_text}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="bento-card" style="height:100%; display:flex; flex-direction:column; justify-content:space-between;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span class="badge-cash">100% КЕШ (USDT SHIELD) ⚪</span>
                <span style="color:#10b981; font-size:12px; font-weight:700;">РИЗИК = 0.0%</span>
            </div>
            <div style="margin: 18px 0; color:#cbd5e1; font-size:14px; line-height:1.5;">
                Капітал повністю у захищеному USDT. Ядро очікує перетину порогу <b>+{config.ENTER_LONG_TH:.2f}</b> при чистоті тренду <b>KER ≥ {config.MIN_KER_ENTRY:.2f}</b>.
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px; color:#64748b; border-top:1px solid rgba(255,255,255,0.06); padding-top:10px;">
                <span>Цільова позиція: <b style="color:#f8fafc;">{telem.get('desired_pos', 0.0):+.2f}x</b></span>
                <span>Crash-Shield: <b style="color:#10b981;">{'АКТИВОВАНО 🚨' if telem.get('crash_shield_active') else 'Норма 🛡️'}</b></span>
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_radar:
    s_u = float(telem.get("signal_ultra", df_snap['Action'].iloc[-1]))
    s_t = float(telem.get("signal_tsmom", 0.0))
    s_p = float(telem.get("signal_pullback", 0.0))
    s_m = float(telem.get("signal_ml", 0.0))
    ker_v = float(telem.get("ker_192", 0.0))
    z96_v = float(telem.get("zscore_96", 0.0))
    imb_v = float(telem.get("taker_imb_96", 0.0))
    news_v = float(telem.get("news_sentiment", 0.0))

    st.markdown(f"""
    <div class="bento-card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <span style="font-weight:700; font-size:14px; color:#38bdf8;">🧬 ДЕКОМПОЗИЦІЯ СИГНАЛУ QUANTCORE V7.8 ULTRA</span>
            <span class="val-mono" style="font-size:16px; font-weight:800; color:{'#10b981' if s_u >= config.ENTER_LONG_TH else '#f8fafc'};">
                MASTER SIGNAL: {s_u:+.3f} (Поріг: +{config.ENTER_LONG_TH:.2f})
            </span>
        </div>
        <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:12px;">
            <div class="core-box">
                <div style="color:#94a3b8; font-size:11px;">1. Macro TSMOM (16d)</div>
                <div class="val-mono" style="font-size:18px; font-weight:700; color:{'#10b981' if s_t>0 else '#ef4444'};">{s_t:+.3f}</div>
                <div style="color:#64748b; font-size:11px;">Spread: {telem.get('spread_macro', 0.0):+.2f}</div>
            </div>
            <div class="core-box">
                <div style="color:#94a3b8; font-size:11px;">2. Pullback Dip-Buyer</div>
                <div class="val-mono" style="font-size:18px; font-weight:700; color:{'#10b981' if s_p>0 else '#94a3b8'};">{s_p:+.3f}</div>
                <div style="color:#64748b; font-size:11px;">Z-Score 24h: {z96_v:+.2f}σ</div>
            </div>
            <div class="core-box">
                <div style="color:#94a3b8; font-size:11px;">3. ML Ensemble (3d)</div>
                <div class="val-mono" style="font-size:18px; font-weight:700; color:{'#38bdf8' if s_m>0 else '#94a3b8'};">{s_m:+.3f}</div>
                <div style="color:#64748b; font-size:11px;">Ridge+LGBM+CatBoost</div>
            </div>
            <div class="core-box">
                <div style="color:#94a3b8; font-size:11px;">4. Orderflow & KER</div>
                <div class="val-mono" style="font-size:18px; font-weight:700; color:{'#10b981' if ker_v>=0.05 else '#f59e0b'};">KER: {ker_v:.3f}</div>
                <div style="color:#64748b; font-size:11px;">Taker Flow: {imb_v:+.2f} | News: {news_v:+.2f}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# --- ГОЛОВНІ АНАЛІТИЧНІ ВКЛАДКИ ---
tab_charts, tab_trades, tab_telemetry = st.tabs([
    "📈 Крива Капіталу та Альфа V7.8",
    "📜 Журнал Ордерів та Комісій",
    "🔬 Посвічковий Аудит Сигналів"
])

with tab_charts:
    fig_eq = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.72, 0.28],
        subplot_titles=("Кумулятивна дохідність: QuantCore V7.8 Ultra vs Buy & Hold BTC (%)", "Підводна крива просадки (Drawdown %)")
    )
    fig_eq.add_trace(go.Scatter(
        x=df_snap['Time'], y=df_snap['Equity_Return_Pct'], mode='lines', name='QuantCore V7.8 Ultra',
        line=dict(color='#10b981', width=2.6), hovertemplate='QuantCore: %{y:+.2f}%<extra></extra>'
    ), row=1, col=1)
    fig_eq.add_trace(go.Scatter(
        x=df_snap['Time'], y=df_snap['BTC_Return_Pct'], mode='lines', name='Buy & Hold BTC',
        line=dict(color='#f59e0b', width=1.5, dash='dot'), hovertemplate='BTC B&H: %{y:+.2f}%<extra></extra>'
    ), row=1, col=1)
    fig_eq.add_trace(go.Scatter(
        x=df_snap['Time'], y=df_snap['Drawdown_Pct'], mode='lines', name='Drawdown',
        line=dict(color='#ef4444', width=1.2), fill='tozeroy', fillcolor='rgba(239, 68, 68, 0.15)',
        hovertemplate='MaxDD: %{y:.2f}%<extra></extra>'
    ), row=2, col=1)
    fig_eq.update_layout(
        template='plotly_dark', height=460, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(15, 23, 42, 0.65)', hovermode='x unified',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_eq, use_container_width=True)

    fig_sig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.68, 0.32],
        subplot_titles=("Котирування BTC/USDT та Точки Виконання Ордерів", "Мастер-Сигнал QuantCore V7.8 та Пороги Гістерезису")
    )
    fig_sig.add_trace(go.Scatter(
        x=df_snap['Time'], y=df_snap['BTC_Price'], mode='lines', name='Ціна BTC',
        line=dict(color='#38bdf8', width=1.8)
    ), row=1, col=1)

    if not df_trades.empty:
        buys = df_trades[df_trades['Side'] == 'BUY']
        sells = df_trades[df_trades['Side'] == 'SELL']
        if not buys.empty:
            fig_sig.add_trace(go.Scatter(
                x=buys['Time'], y=buys['Price'], mode='markers', name='BUY (Entry/Boost)',
                marker=dict(symbol='triangle-up', size=12, color='#10b981', line=dict(width=1, color='#ffffff'))
            ), row=1, col=1)
        if not sells.empty:
            fig_sig.add_trace(go.Scatter(
                x=sells['Time'], y=sells['Price'], mode='markers', name='SELL (Exit to Cash)',
                marker=dict(symbol='triangle-down', size=12, color='#ef4444', line=dict(width=1, color='#ffffff'))
            ), row=1, col=1)

    bar_colors = ['#10b981' if a >= config.ENTER_LONG_TH else ('#38bdf8' if a > config.EXIT_LONG_TH else '#64748b') for a in df_snap['Action']]
    fig_sig.add_trace(go.Bar(
        x=df_snap['Time'], y=df_snap['Action'], name='Сигнал V7.8', marker_color=bar_colors
    ), row=2, col=1)
    fig_sig.add_hline(y=config.ENTER_LONG_TH, line_dash="dot", line_color="#10b981", annotation_text="Вхід Long (+0.35)", row=2, col=1)
    fig_sig.add_hline(y=config.EXIT_LONG_TH, line_dash="dot", line_color="#ef4444", annotation_text="Вихід Cash (-0.05)", row=2, col=1)
    fig_sig.update_layout(
        template='plotly_dark', height=440, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(15, 23, 42, 0.65)', hovermode='x unified',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_sig, use_container_width=True)

with tab_trades:
    if not df_trades.empty:
        c_info, c_dl = st.columns([3, 1])
        c_info.markdown(f"**Всього виконаних ордерів:** `{len(df_trades)}` | **Сумарна комісія:** `${total_fees:.2f}` | **Чистий реалізований профіт:** `${net_realized_pnl:+,.2f}`")
        c_dl.download_button("📥 Завантажити CSV", data=df_trades.to_csv(index=False).encode('utf-8'), file_name="quantcore_v7_8_trades.csv", mime="text/csv", use_container_width=True)

        vt = df_trades.copy()
        vt['Time'] = vt['Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        vt['Price'] = vt['Price'].map('\${:,.1f}'.format)
        vt['Amount'] = vt['Amount'].map('{:.3f} BTC'.format)
        vt['PnL'] = vt['PnL'].map('\${:+,.2f}'.format)
        vt['Fee'] = vt['Fee'].map('\${:.3f}'.format)
        vt['Net_PnL'] = vt['Net_PnL'].map('\${:+,.2f}'.format)
        st.dataframe(vt, use_container_width=True, hide_index=True)
    else:
        st.info("У вибраному часовому діапазоні угод ще не зафіксовано.")

with tab_telemetry:
    vs = df_snap[['Time', 'BTC_Price', 'Action', 'Position', 'Equity', 'Unrealized_PnL', 'Drawdown_Pct']].tail(50).iloc[::-1].copy()
    vs['Time'] = vs['Time'].dt.strftime('%Y-%m-%d %H:%M')
    vs['BTC_Price'] = vs['BTC_Price'].map('\${:,.1f}'.format)
    vs['Action'] = vs['Action'].map('{:+.4f}'.format)
    vs['Position'] = vs['Position'].map('{:+.3f} BTC'.format)
    vs['Equity'] = vs['Equity'].map('\${:,.2f}'.format)
    vs['Unrealized_PnL'] = vs['Unrealized_PnL'].map('\${:+,.2f}'.format)
    vs['Drawdown_Pct'] = vs['Drawdown_Pct'].map('{:.2f}%'.format)
    st.dataframe(vs, use_container_width=True, hide_index=True)