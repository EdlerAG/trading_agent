import io
import os
import gc
import json
import html
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

import config
from exchange import get_exchange, get_current_position_status, emergency_close_all
from database import engine, SessionLocal, EquitySnapshot, Trade, get_daily_pnl
from news_agent import get_news_sentiment, fetch_latest_crypto_headlines

STATE_FILE = getattr(config, "STATE_FILE", os.path.join(config.BASE_DIR, "bot_state.json"))
DASHBOARD_URL = getattr(config, "DASHBOARD_URL", "http://localhost:8501")

# Глобальна подія для миттєвого пробудження main.py при зміні налаштувань з Telegram
WAKEUP_EVENT = threading.Event()

_TG_SESSION = requests.Session()
_TG_SESSION.headers.update({"Connection": "keep-alive"})


# ==========================================
# 1. АТОМАРНА ПЕРСИСТЕНТНІСТЬ СТАНУ ТА ТЕЛЕМЕТРІЇ
# ==========================================
def save_bot_state(extra_telemetry: dict = None):
    """Атомарно зберігає стан позиції, активний SL та телеметрію всіх 4 ядер."""
    existing = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    telemetry = existing.get("telemetry", {})
    if extra_telemetry:
        telemetry.update(extra_telemetry)

    state = {
        "IS_PAUSED": config.IS_PAUSED,
        "PAUSE_UNTIL": config.PAUSE_UNTIL.isoformat() if config.PAUSE_UNTIL else None,
        "RISK_PROFILE": getattr(config, "RISK_PROFILE", "OPTIMAL"),
        "TIER1_SIZE": getattr(config, "TIER1_SIZE", 0.80),
        "MAX_CONVICTION_SIZE": getattr(config, "MAX_CONVICTION_SIZE", 1.30),
        "TRADE_ENTRY_PRICE": config.TRADE_ENTRY_PRICE,
        "TRADE_CANDLES_COUNT": config.TRADE_CANDLES_COUNT,
        "IS_BREAKEVEN_TRIGGERED": config.IS_BREAKEVEN_TRIGGERED,
        "INITIAL_TRADE_AMOUNT": getattr(config, "INITIAL_TRADE_AMOUNT", 0.0),
        "ACTIVE_SL_PRICE": getattr(config, "ACTIVE_SL_PRICE", 0.0),
        "force_step": existing.get("force_step", False),
        "telemetry": telemetry,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        tmp_file = STATE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        config.logger.warning(f"Не вдалося зберегти стан бота в {STATE_FILE}: {e}")


def load_bot_state() -> dict:
    """Синхронізує пам'ять бота зі змінами у bot_state.json (включно з командами веб-дашборду)."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        config.IS_PAUSED = bool(state.get("IS_PAUSED", False))
        if state.get("PAUSE_UNTIL"):
            config.PAUSE_UNTIL = datetime.fromisoformat(state["PAUSE_UNTIL"])
        else:
            config.PAUSE_UNTIL = None

        saved_prof = str(state.get("RISK_PROFILE", config.RISK_PROFILE)).upper()
        if saved_prof in config.RISK_PROFILES_MAP:
            config.RISK_PROFILE = saved_prof
            config.TIER1_SIZE, config.MAX_CONVICTION_SIZE = config.RISK_PROFILES_MAP[saved_prof]

        config.TRADE_ENTRY_PRICE = float(state.get("TRADE_ENTRY_PRICE", 0.0))
        config.TRADE_CANDLES_COUNT = int(state.get("TRADE_CANDLES_COUNT", 0))
        config.IS_BREAKEVEN_TRIGGERED = bool(state.get("IS_BREAKEVEN_TRIGGERED", False))
        config.INITIAL_TRADE_AMOUNT = float(state.get("INITIAL_TRADE_AMOUNT", 0.0))
        config.ACTIVE_SL_PRICE = float(state.get("ACTIVE_SL_PRICE", 0.0))
        return state
    except Exception as e:
        config.logger.warning(f"Помилка зчитування bot_state.json: {e}")
        return {}


def _render_bar(val: float, low: float = -1.0, high: float = 1.0, width: int = 10) -> str:
    """Генерує стильний текстовий індикатор прогресу для Telegram."""
    norm = (val - low) / max(1e-6, (high - low))
    norm = max(0.0, min(1.0, norm))
    filled = int(round(norm * width))
    return "▰" * filled + "▱" * (width - filled)


# ==========================================
# 2. ІНТЕРАКТИВНІ КЛАВІАТУРИ QUANTCORE V7.8
# ==========================================
def get_main_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "📊 Статус V7.8", "callback_data": "cmd_status"},
                {"text": "🧬 Радар 4 Ядер", "callback_data": "cmd_radar"}
            ],
            [
                {"text": "📈 Графік Альфи", "callback_data": "cmd_chart"},
                {"text": "📜 Історія угод", "callback_data": "cmd_history"}
            ],
            [
                {"text": "⚙️ Профіль Ризику", "callback_data": "cmd_risk_menu"},
                {"text": "⚡ Перерахувати свічку", "callback_data": "cmd_force_step"}
            ],
            [
                {"text": "📰 Сентимент Gemini", "callback_data": "cmd_news_test"},
                {"text": "📋 Логи (15 рядків)", "callback_data": "cmd_logs"}
            ],
            [
                {"text": "⏸️ Пауза", "callback_data": "cmd_pause_menu"},
                {"text": "▶️ Відновити", "callback_data": "cmd_resume"},
                {"text": "🏓 Ping", "callback_data": "cmd_ping"}
            ],
            [
                {"text": "🚨 Закрити все в USDT", "callback_data": "cmd_close_confirm"},
                {"text": "🌐 Web-Термінал", "url": DASHBOARD_URL}
            ]
        ]
    }


def get_risk_keyboard():
    cur = getattr(config, "RISK_PROFILE", "OPTIMAL")
    return {
        "inline_keyboard": [
            [{"text": f"{'✅ ' if cur=='CONSERVATIVE' else ''}🛡️ Conservative (0.75x..1.0x | DD -12.5%)", "callback_data": "cmd_risk_cons"}],
            [{"text": f"{'✅ ' if cur=='OPTIMAL' else ''}⚖️ Optimal (0.80x..1.30x | +33.0% Net)", "callback_data": "cmd_risk_opt"}],
            [{"text": f"{'✅ ' if cur=='AGGRESSIVE' else ''}🔥 Aggressive (1.00x..1.50x | +38.1% Net)", "callback_data": "cmd_risk_agg"}],
            [{"text": "🔙 Назад у головне меню", "callback_data": "cmd_status"}]
        ]
    }


def get_pause_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "⏸️ 1 година", "callback_data": "cmd_pause_1h"},
                {"text": "⏸️ 8 годин", "callback_data": "cmd_pause_8h"}
            ],
            [
                {"text": "⏸️ 24 години", "callback_data": "cmd_pause_24h"},
                {"text": "🛑 Безстроково", "callback_data": "cmd_pause_inf"}
            ],
            [{"text": "🔙 Назад", "callback_data": "cmd_status"}]
        ]
    }


def get_confirmation_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "✅ ТАК, ЛІКВІДУВАТИ В КЕШ", "callback_data": "cmd_close_execute"},
                {"text": "❌ Скасувати", "callback_data": "cmd_status"}
            ]
        ]
    }


# ==========================================
# 3. БАЗОВІ ФУНКЦІЇ TELEGRAM API
# ==========================================
def send_telegram_alert(text: str, reply_markup=None):
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup if reply_markup else get_main_keyboard(),
        "disable_web_page_preview": True
    }
    try:
        _TG_SESSION.post(url, json=payload, timeout=8)
    except Exception as e:
        config.logger.error(f"Помилка надсилання повідомлення в Telegram: {e}")


def send_telegram_document(file_path: str, caption: str = ""):
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID or not os.path.exists(file_path):
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            files = {'document': (os.path.basename(file_path), f)}
            data = {'chat_id': config.TELEGRAM_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
            _TG_SESSION.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        config.logger.error(f"Помилка відправки документа в Telegram: {e}")


def answer_callback_query(callback_query_id: str, text: str = ""):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/answerCallbackQuery"
    try:
        _TG_SESSION.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=3)
    except Exception:
        pass


# ==========================================
# 4. АНАЛІТИЧНІ ЗВІТИ ТА РАДАР ЯДЕР V7.8 ULTRA
# ==========================================
def build_status_message() -> str:
    state = load_bot_state()
    telem = state.get("telemetry", {})

    exchange = get_exchange()
    current_btc, usdt_balance, entry_price, unrealized_pnl = get_current_position_status(exchange)

    try:
        ticker = exchange.fetch_ticker(config.SYMBOL)
        current_price = float(ticker.get('last') or telem.get('price') or 0.0)
    except Exception:
        current_price = float(telem.get('price') or 0.0)

    total_equity = max(0.0, usdt_balance + unrealized_pnl)
    daily_pnl = get_daily_pnl()

    status_icon = "🟢"
    status_label = "АКТИВНИЙ (15m Sync)"
    if config.IS_PAUSED:
        status_icon = "⏸️"
        status_label = f"ПАУЗА (до {config.PAUSE_UNTIL.strftime('%H:%M UTC')})" if config.PAUSE_UNTIL else "БЕЗСТРОКОВА ПАУЗА"

    sig_ultra = float(telem.get("signal_ultra", 0.0))
    en_th = float(telem.get("enter_long_th", config.ENTER_LONG_TH))
    ex_th = float(telem.get("exit_long_th", config.EXIT_LONG_TH))

    if abs(current_btc) >= config.MIN_TRADE_BTC:
        pos_dir = "LONG 🟢" if current_btc > 0 else "SHORT 🔴"
        notional = abs(current_btc) * current_price
        eff_lev = notional / total_equity if total_equity > 0 else 0.0
        pnl_pct = (unrealized_pnl / max(1.0, notional)) * 100.0
        pnl_sign = "+" if unrealized_pnl >= 0 else ""
        sl_p = getattr(config, "ACTIVE_SL_PRICE", 0.0)
        sl_str = f"${sl_p:,.1f} ({'Безубиток 🛡️' if config.IS_BREAKEVEN_TRIGGERED else 'Mark Price SL'})" if sl_p > 0 else "Очікування"

        pos_info = (
            f"<b>Відкрита позиція:</b> {pos_dir} (<b>{eff_lev:.2f}x</b>)\n"
            f"• Контракт: <code>{abs(current_btc):.3f} BTC</code> (~${notional:,.1f})\n"
            f"• Ціна входу: <code>${entry_price:,.1f}</code>\n"
            f"• Unrealized PnL: <b>{pnl_sign}${unrealized_pnl:.2f}</b> ({pnl_sign}{pnl_pct:.2f}%)\n"
            f"• Захисний стоп: <code>{sl_str}</code>\n"
            f"• Утримання тренду: <code>{config.TRADE_CANDLES_COUNT} свічок</code> (~{config.TRADE_CANDLES_COUNT * 15 / 60:.1f} год)"
        )
    else:
        pos_info = (
            f"<b>Позиція:</b> <b>100% КЕШ (USDT) ⚪</b>\n"
            f"• Капітал захищено від просадки. Очікування імпульсу ≥ <code>+{en_th:.2f}</code>"
        )

    msg = (
        f"⚡ <b>ТЕРМІНАЛ QUANTCORE V7.8 ULTRA</b>\n"
        f"═══════════════════════\n"
        f"• <b>Статус:</b> {status_icon} {status_label}\n"
        f"• <b>Профіль ризику:</b> <code>{config.RISK_PROFILE} ({config.TIER1_SIZE:.2f}x..{config.MAX_CONVICTION_SIZE:.2f}x)</code>\n"
        f"• <b>Котирування BTC:</b> <code>${current_price:,.1f}</code>\n"
        f"• <b>Сумарний капітал (Equity):</b> <b>${total_equity:,.2f} USDT</b>\n"
        f"• <b>Вільна маржа:</b> <code>${usdt_balance:,.2f} USDT</code>\n"
        f"• <b>Реалізований PnL (24г):</b> <code>{daily_pnl:+.2f} USDT</code>\n"
        f"───────────────────────\n"
        f"{pos_info}\n"
        f"───────────────────────\n"
        f"• <b>Сигнал V7.8:</b> <b>{sig_ultra:+.3f}</b>  [{_render_bar(sig_ultra, -0.4, 1.0, 8)}]\n"
        f"• <b>Пороги:</b> Вхід <code>+{en_th:.2f}</code> | Вихід <code>{ex_th:+.2f}</code>\n"
        f"═══════════════════════\n"
        f"🕒 <i>{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC')}</i>"
    )
    return msg


def build_radar_message() -> str:
    """Детальна декомпозиція всіх 4 ядер та факторів ринкового режиму V7.8."""
    state = load_bot_state()
    t = state.get("telemetry", {})
    if not t:
        return "⏳ <b>Телеметрія ще формується...</b> Зачекайте першого розрахунку свічки."

    s_ultra = float(t.get("signal_ultra", 0.0))
    s_tsmom = float(t.get("signal_tsmom", 0.0))
    s_pull = float(t.get("signal_pullback", 0.0))
    s_ml = float(t.get("signal_ml", 0.0))
    ker = float(t.get("ker_192", 0.0))
    vr = float(t.get("vol_ratio", 1.0))
    z96 = float(t.get("zscore_96", 0.0))
    taker = float(t.get("taker_imb_96", 0.0))
    donch = float(t.get("donchian_768", 0.0))
    news = float(t.get("news_sentiment", 0.0))
    crash = bool(t.get("crash_shield_active", False))

    ker_status = "🟢 Чистий тренд" if ker >= config.MIN_KER_ENTRY else "⚠️ Флет (Блок входу)"
    crash_status = "🚨 АКТИВОВАНО (Cash Veto!)" if crash else "🟢 Спокійно (Норма)"
    dip_status = "🔥 АКТИВНИЙ ДОБІР (Dip < -0.6)" if z96 < -0.60 else "Нейтрально"

    msg = (
        f"🧬 <b>РАДАР АЛЬФА-ЯДЕР QUANTCORE V7.8</b>\n"
        f"═══════════════════════\n"
        f"<b>1. Мастер-Сигнал V7.8 Ultra:</b> <b>{s_ultra:+.3f}</b>\n"
        f"   <code>[{_render_bar(s_ultra, -0.3, 1.0, 12)}]</code> (Ціль: <b>{t.get('desired_pos', 0.0):+.2f}x</b>)\n\n"
        f"<b>2. Декомпозиція суб-ядер:</b>\n"
        f"• <b>Macro TSMOM (1d..16d):</b> <code>{s_tsmom:+.3f}</code>  [{_render_bar(s_tsmom, -1, 1, 6)}]\n"
        f"• <b>Pullback Dip-Buyer:</b>   <code>{s_pull:+.3f}</code>  [{_render_bar(s_pull, -1, 1, 6)}]\n"
        f"• <b>ML Ensemble (3d EV):</b>  <code>{s_ml:+.3f}</code>  [{_render_bar(s_ml, -1, 1, 6)}]\n"
        f"───────────────────────\n"
        f"<b>3. Ринкова структура та Фільтри:</b>\n"
        f"• <b>Індекс чистоти тренду (KER):</b> <code>{ker:.3f}</code> ({ker_status})\n"
        f"• <b>Pullback Z-Score (24h):</b> <code>{z96:+.2f}σ</code> ({dip_status})\n"
        f"• <b>Taker Buy Orderflow:</b> <code>{taker:+.2f}</code>\n"
        f"• <b>Канал Дончіана (8d):</b> <code>{donch:+.2f}</code>\n"
        f"• <b>Режим волатильності:</b> <code>{vr:.2f}x</code> (ATR: <code>${t.get('atr', 0):,.1f}</code>)\n"
        f"• <b>Crash-Shield захист:</b> {crash_status}\n"
        f"• <b>Новинний фон Gemini:</b> <code>{news:+.2f}</code>\n"
        f"═══════════════════════\n"
        f"🕯 <i>Свічка: {t.get('timestamp', 'N/A')} UTC</i>"
    )
    return msg


def send_equity_chart():
    """Lazy-імпорт Matplotlib тільки на момент генерації PNG з подальшим очищенням RAM."""
    try:
        df = pd.read_sql_query(
            "SELECT timestamp, balance_usdt, position_btc, btc_price, total_equity, unrealized_pnl, model_action "
            "FROM equity_snapshots ORDER BY timestamp ASC",
            engine
        )
        if len(df) < 2:
            send_telegram_alert("📉 Недостатньо даних для побудови графіка (мінімум 2 закриті свічки).")
            return

        df['time'] = pd.to_datetime(df['timestamp'])
        df['equity'] = np.where(
            df['total_equity'].notnull() & (df['total_equity'] > 0),
            df['total_equity'],
            df['balance_usdt'] + df['unrealized_pnl'].fillna(0.0)
        )

        start_eq = float(df['equity'].iloc[0])
        curr_eq = float(df['equity'].iloc[-1])
        net_ret_pct = ((curr_eq / start_eq) - 1.0) * 100.0 if start_eq > 0 else 0.0

        start_btc = float(df['btc_price'].iloc[0])
        df['eq_pct'] = ((df['equity'] / start_eq) - 1.0) * 100.0
        df['btc_pct'] = ((df['btc_price'] / start_btc) - 1.0) * 100.0

        peak = df['equity'].cummax()
        dd_pct = ((df['equity'] - peak) / peak) * 100.0
        max_dd = float(dd_pct.min())

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True, gridspec_kw={'height_ratios': [2.6, 1.2]})
        fig.patch.set_facecolor('#0b0f19')

        for ax in (ax1, ax2):
            ax.set_facecolor('#111827')
            ax.tick_params(colors='#94a3b8', labelsize=8.5)
            ax.grid(True, linestyle='--', alpha=0.14, color='#cbd5e1')
            for spine in ax.spines.values():
                spine.set_color('#1e293b')

        ax1.plot(df['time'], df['eq_pct'], color='#10b981', linewidth=2.2, label=f'QuantCore V7.8 ({net_ret_pct:+.2f}%)')
        ax1.plot(df['time'], df['btc_pct'], color='#f59e0b', linewidth=1.3, linestyle='--', alpha=0.85, label='Buy & Hold BTC (%)')
        ax1.fill_between(df['time'], df['eq_pct'], df['btc_pct'], where=(df['eq_pct'] >= df['btc_pct']), color='#10b981', alpha=0.10)
        ax1.set_ylabel('Дохідність (%)', color='#cbd5e1', fontsize=9.5)
        ax1.legend(loc='upper left', facecolor='#0b0f19', edgecolor='#334155', labelcolor='white', fontsize=8.5)
        ax1.set_title('QUANTCORE V7.8 ULTRA: ALPHA vs BTC BUY & HOLD', color='#f8fafc', fontsize=11, pad=10, weight='bold')

        ax2.plot(df['time'], df['model_action'], color='#38bdf8', linewidth=1.5, label='Сигнал V7.8')
        ax2.axhline(config.ENTER_LONG_TH, color='#10b981', linestyle=':', linewidth=1.0, label=f'Вхід (+{config.ENTER_LONG_TH})')
        ax2.axhline(config.EXIT_LONG_TH, color='#ef4444', linestyle=':', linewidth=1.0, label=f'Вихід ({config.EXIT_LONG_TH})')
        ax2.set_ylabel('Сигнал ядра', color='#cbd5e1', fontsize=9)
        ax2.legend(loc='upper left', facecolor='#0b0f19', edgecolor='#334155', labelcolor='white', fontsize=8)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
        fig.autofmt_xdate()
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=135, facecolor=fig.get_facecolor(), edgecolor='none')
        buf.seek(0)
        plt.close(fig)

        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendPhoto"
        files = {'photo': ('quantcore_v7_8.png', buf, 'image/png')}
        data = {
            'chat_id': config.TELEGRAM_CHAT_ID,
            'caption': (
                f"📈 <b>Звіт ефективності QuantCore V7.8 Ultra:</b>\n"
                f"• Капітал (Equity): <b>${curr_eq:,.2f} USDT</b> (<b>{net_ret_pct:+.2f}%</b>)\n"
                f"• Максимальна просадка: <b>{max_dd:.2f}%</b>\n"
                f"• Профіль: <code>{config.RISK_PROFILE}</code>"
            ),
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(get_main_keyboard())
        }
        _TG_SESSION.post(url, data=data, files=files, timeout=20)
        buf.close()
        gc.collect()

    except Exception as e:
        config.logger.error(f"Помилка побудови графіка: {e}", exc_info=True)
        send_telegram_alert(f"❌ Не вдалося створити графік: {e}")


def send_trade_history():
    session = SessionLocal()
    try:
        trades = session.query(Trade).order_by(Trade.timestamp.desc()).limit(7).all()
        if not trades:
            send_telegram_alert("📜 Історія біржових операцій поки порожня.")
            return

        lines = ["📜 <b>ОСТАННІ ОПЕРАЦІЇ QUANTCORE V7.8:</b>\n═══════════════════════"]
        for t in trades:
            side_icon = "🟢 BUY" if t.side.upper() == "BUY" else "🔴 SELL"
            pnl_str = f" | PnL: <b>{t.realized_pnl:+.2f}$</b>" if t.realized_pnl != 0.0 else ""
            fee_str = f" | Fee: {t.fee_usdt:.2f}$" if getattr(t, 'fee_usdt', None) else ""
            t_time = t.timestamp.strftime('%d.%m %H:%M')

            lines.append(
                f"• <code>{t_time}</code> | {side_icon} <b>{t.amount_btc:.3f} BTC</b> @ <code>${t.price:,.1f}</code>{pnl_str}{fee_str}\n"
                f"  <i>{html.escape(t.note or 'QuantCore Execution')}</i>"
            )
        lines.append("═══════════════════════")
        send_telegram_alert("\n".join(lines))
    except Exception as e:
        send_telegram_alert(f"❌ Помилка читання історії: {e}")
    finally:
        session.close()


def send_server_logs():
    if not os.path.exists(config.LOG_PATH):
        send_telegram_alert("📋 Лог-файл ще не створено.")
        return
    try:
        with open(config.LOG_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-15:]
            clean_log = html.escape("".join(lines))
        send_telegram_alert(f"📋 <b>ОСТАННІ 15 РЯДКІВ ЛОГУ:</b>\n<pre>{clean_log[-3500:]}</pre>")
    except Exception as e:
        send_telegram_alert(f"❌ Помилка читання логів: {e}")


def test_gemini_news():
    send_telegram_alert("⏳ <i>Оновлення заголовків RSS та аналіз через Gemini AI...</i>")
    try:
        headlines = fetch_latest_crypto_headlines(force_refresh=True)
        score = get_news_sentiment(force_refresh=True)

        if not headlines:
            send_telegram_alert("⚠️ RSS-стрічки тимчасово недоступні.")
            return

        titles_str = "\n".join([f"• {html.escape(h[:80])}" for h in headlines[:5]])
        verdict = "БИЧАЧИЙ 🟢" if score > 0.15 else ("ВЕДМЕЖИЙ 🔴" if score < -0.15 else "НЕЙТРАЛЬНИЙ ⚪")

        msg = (
            f"📰 <b> АНАЛІТИКА НОВИН GEMINI AI</b>\n"
            f"═══════════════════════\n"
            f"• <b>Індекс сентименту:</b> <b>{score:+.2f}</b> ({verdict})\n"
            f"• <b>Вплив на V7.8:</b> {'Активний захист' if score <= -0.75 else 'Штатний режим'}\n"
            f"───────────────────────\n"
            f"{titles_str}\n"
            f"═══════════════════════"
        )
        send_telegram_alert(msg)
    except Exception as e:
        send_telegram_alert(f"❌ Збій тесту новин: {html.escape(str(e))}")


def check_exchange_ping():
    exchange = get_exchange()
    t0 = time.time()
    try:
        exchange.fetch_time()
        ms = (time.time() - t0) * 1000.0
        send_telegram_alert(f"🏓 <b>Pong!</b> Затримка до ядра Binance Futures: <b>{ms:.1f} мс</b>.")
    except Exception as e:
        send_telegram_alert(f"❌ Помилка мережі біржі: {html.escape(str(e))}")


def set_risk_profile(new_profile: str):
    if new_profile in config.RISK_PROFILES_MAP:
        config.RISK_PROFILE = new_profile
        config.TIER1_SIZE, config.MAX_CONVICTION_SIZE = config.RISK_PROFILES_MAP[new_profile]
        save_bot_state()
        WAKEUP_EVENT.set()
        send_telegram_alert(
            f"✅ <b>Профіль ризику змінено на: {new_profile}!</b>\n\n"
            f"• Базовий вхід (Tier 1): <b>{config.TIER1_SIZE:.2f}x</b>\n"
            f"• Макс. переконання (Dip-Boost): <b>{config.MAX_CONVICTION_SIZE:.2f}x</b>",
            reply_markup=get_risk_keyboard()
        )


# ==========================================
# 5. ДИСПЕТЧЕР КОМАНД
# ==========================================
def handle_command(cmd: str):
    cmd = cmd.strip()
    config.logger.info(f"Команда Telegram: {cmd}")

    if cmd in ["/start", "cmd_status", "/status"]:
        send_telegram_alert(build_status_message())
    elif cmd in ["/radar", "cmd_radar"]:
        send_telegram_alert(build_radar_message())
    elif cmd in ["/chart", "cmd_chart"]:
        send_equity_chart()
    elif cmd in ["/history", "cmd_history"]:
        send_trade_history()
    elif cmd in ["/logs", "cmd_logs"]:
        send_server_logs()
    elif cmd == "cmd_get_logfile":
        if os.path.exists(config.LOG_PATH):
            send_telegram_document(config.LOG_PATH, caption="📥 <b>Повний системний лог QuantCore V7.8</b>")
    elif cmd in ["/news", "cmd_news_test"]:
        test_gemini_news()
    elif cmd in ["/ping", "cmd_ping"]:
        check_exchange_ping()
    elif cmd == "cmd_risk_menu":
        send_telegram_alert("⚙️ <b>Оберіть профіль розподілу капіталу QuantCore V7.8:</b>", reply_markup=get_risk_keyboard())
    elif cmd == "cmd_risk_cons":
        set_risk_profile("CONSERVATIVE")
    elif cmd == "cmd_risk_opt":
        set_risk_profile("OPTIMAL")
    elif cmd == "cmd_risk_agg":
        set_risk_profile("AGGRESSIVE")
    elif cmd == "cmd_force_step":
        WAKEUP_EVENT.set()
        send_telegram_alert("⚡ <b>Запит на позачерговий розрахунок відправлено!</b> Ядро оновлює свічки...")
    elif cmd in ["/pause", "cmd_pause_menu"]:
        send_telegram_alert("⏸️ <b>Оберіть тривалість паузи торгівлі:</b>", reply_markup=get_pause_keyboard())
    elif cmd == "cmd_pause_1h":
        config.IS_PAUSED = True
        config.PAUSE_UNTIL = datetime.now(timezone.utc) + timedelta(hours=1)
        save_bot_state()
        send_telegram_alert(f"⏸️ <b>Пауза на 1 годину</b> (до {config.PAUSE_UNTIL.strftime('%H:%M UTC')}).")
    elif cmd == "cmd_pause_8h":
        config.IS_PAUSED = True
        config.PAUSE_UNTIL = datetime.now(timezone.utc) + timedelta(hours=8)
        save_bot_state()
        send_telegram_alert(f"⏸️ <b>Пауза на 8 годин</b> (до {config.PAUSE_UNTIL.strftime('%H:%M UTC')}).")
    elif cmd == "cmd_pause_24h":
        config.IS_PAUSED = True
        config.PAUSE_UNTIL = datetime.now(timezone.utc) + timedelta(hours=24)
        save_bot_state()
        send_telegram_alert(f"⏸️ <b>Пауза на 24 години</b> (до {config.PAUSE_UNTIL.strftime('%d.%m %H:%M UTC')}).")
    elif cmd == "cmd_pause_inf":
        config.IS_PAUSED = True
        config.PAUSE_UNTIL = None
        save_bot_state()
        send_telegram_alert("🛑 <b>Бота поставлено на БЕЗСТРОКОВУ паузу.</b>")
    elif cmd in ["/resume", "cmd_resume"]:
        config.IS_PAUSED = False
        config.PAUSE_UNTIL = None
        save_bot_state()
        WAKEUP_EVENT.set()
        send_telegram_alert("▶️ <b>Торгівлю відновлено!</b> Алгоритм QuantCore V7.8 Ultra активний.")
    elif cmd == "cmd_close_confirm":
        send_telegram_alert(
            "⚠️ <b>ПІДТВЕРДЖЕННЯ ЕКСТРЕНОГО ВИХОДУ В USDT!</b>\n\n"
            "Поточна позиція буде миттєво закрита за ринком, а всі ордери скасовані.",
            reply_markup=get_confirmation_keyboard()
        )
    elif cmd == "cmd_close_execute":
        res = emergency_close_all()
        save_bot_state()
        send_telegram_alert(f"🚨 <b>Екстрений вихід виконано!</b>\n\n{res}")


# ==========================================
# 6. ZERO-CPU LONG POLLING СЛУХАЧ (TIMEOUT 50s)
# ==========================================
def telegram_listener():
    last_update_id = None
    config.logger.info("📱 Telegram Long-Polling (Zero-Idle CPU Mode) активовано.")
    load_bot_state()

    while True:
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
            params = {
                "timeout": 50,
                "offset": last_update_id,
                "allowed_updates": json.dumps(["message", "callback_query"])
            }
            resp = _TG_SESSION.get(url, params=params, timeout=55)

            if resp.status_code != 200:
                time.sleep(5)
                continue

            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue

            for item in data.get("result", []):
                last_update_id = item["update_id"] + 1

                if "callback_query" in item:
                    cq = item["callback_query"]
                    chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
                    if chat_id == str(config.TELEGRAM_CHAT_ID):
                        answer_callback_query(cq["id"])
                        handle_command(cq.get("data", ""))

                elif "message" in item:
                    msg = item["message"]
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text = (msg.get("text") or "").strip()
                    if chat_id == str(config.TELEGRAM_CHAT_ID) and text:
                        handle_command(text)

        except requests.exceptions.ReadTimeout:
            continue
        except Exception as e:
            config.logger.warning(f"Збій мережі Telegram Polling: {e}")
            time.sleep(5)