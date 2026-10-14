import os
import gc
import time
import joblib
import threading
import traceback
from datetime import datetime, timezone

import config
from exchange import get_exchange, fetch_historical_candles
from features import compute_quant_core_signal_and_target
from news_agent import get_news_sentiment
from telegram_bot import (
    telegram_listener,
    send_telegram_alert,
    send_telegram_document,
    load_bot_state,
    save_bot_state,
    WAKEUP_EVENT
)
from database import init_db, record_snapshot, cleanup_old_data
from execution import execute_rebalance, sync_orders_and_position, check_circuit_breaker

LAST_BACKUP_DATE = None
LAST_PROCESSED_CANDLE_TS = None


def safe_send_telegram(message: str):
    try:
        send_telegram_alert(message)
    except Exception as e:
        config.logger.warning(f"Не вдалося надіслати сповіщення в Telegram: {e}")


def check_daily_maintenance():
    global LAST_BACKUP_DATE
    today = datetime.now(timezone.utc).date()

    if LAST_BACKUP_DATE is None:
        LAST_BACKUP_DATE = today
        return

    if today > LAST_BACKUP_DATE:
        db_path = getattr(config, "DB_PATH", os.path.join(config.BASE_DIR, "trading_history.db"))
        if os.path.exists(db_path):
            try:
                caption = (
                    f"📦 <b>Щоденний авто-бекап БД QuantCore V7.8 Ultra</b>\n"
                    f"Дата: {today.strftime('%d.%m.%Y')}"
                )
                send_telegram_document(db_path, caption=caption)
            except Exception as e:
                config.logger.error(f"Помилка створення бекапу в Telegram: {e}")

        try:
            cleanup_old_data(days_to_keep=90)
        except Exception as e:
            config.logger.warning(f"Помилка планового очищення БД: {e}")

        LAST_BACKUP_DATE = today


def run_trading_step(bundle: dict, force_recalc: bool = False):
    """Головний торговий крок QuantCore V7.8 Ultra."""
    global LAST_PROCESSED_CANDLE_TS
    t0 = time.time()

    # Синхронізуємо можливі зміни налаштувань із Веб-Дашборду чи Telegram
    disk_state = load_bot_state()
    if disk_state.get("force_step"):
        force_recalc = True
        disk_state["force_step"] = False
        save_bot_state()

    if config.IS_PAUSED:
        if config.PAUSE_UNTIL:
            if datetime.now(timezone.utc) >= config.PAUSE_UNTIL:
                config.IS_PAUSED = False
                config.PAUSE_UNTIL = None
                save_bot_state()
                safe_send_telegram("▶️ <b>Час паузи вичерпано.</b> QuantCore V7.8 відновив штатну торгівлю!")
            else:
                config.logger.info(f"⏸️ Бот на паузі до {config.PAUSE_UNTIL.strftime('%H:%M')} UTC. Пропуск.")
                return
        else:
            config.logger.info("⏸️ Бот на безстроковій паузі. Пропуск свічки.")
            return

    check_daily_maintenance()

    news_score = 0.0
    if getattr(config, "ENABLE_NEWS_SENTIMENT", True):
        try:
            news_score = float(get_news_sentiment())
        except Exception as e:
            config.logger.warning(f"⚠️ Збій новинного модуля: {e}")

    raw_df = fetch_historical_candles(limit=config.CANDLES_FETCH_LIMIT)
    if raw_df is None or len(raw_df) < 1800:
        config.logger.error(f"Недостатньо свічок від біржі ({0 if raw_df is None else len(raw_df)} < 1800). Пропуск.")
        return

    candle_ts = str(raw_df['timestamp'].iloc[-1])
    if not force_recalc and LAST_PROCESSED_CANDLE_TS == candle_ts:
        return

    exchange = get_exchange()
    current_btc, usdt_balance, entry_price, unrealized_pnl_usd = sync_orders_and_position(exchange)
    current_price = float(raw_df['close'].iloc[-1])

    total_equity = max(10.0, usdt_balance + unrealized_pnl_usd)
    check_circuit_breaker(total_equity)
    if config.IS_PAUSED:
        return

    current_pos_norm = (current_btc * current_price) / total_equity if total_equity > 0 else 0.0

    signal_val, desired_pos, telemetry = compute_quant_core_signal_and_target(
        df=raw_df,
        bundle=bundle,
        current_pos_norm=current_pos_norm,
        bars_held=config.TRADE_CANDLES_COUNT,
        news_sentiment=news_score
    )

    current_atr = float(telemetry["atr"])
    calc_ms = (time.time() - t0) * 1000.0

    config.logger.info(
        f"⚡ [{candle_ts} | {calc_ms:.0f}ms] BTC: ${current_price:,.1f} | Сигнал V7.8: {signal_val:+.3f} "
        f"(TSMOM:{telemetry['signal_tsmom']:+.2f}, Pull:{telemetry['signal_pullback']:+.2f}, ML:{telemetry['signal_ml']:+.2f}) | "
        f"KER:{telemetry['ker_192']:.2f} | Z96:{telemetry['zscore_96']:+.2f} | "
        f"Поз: {current_pos_norm:+.2f}x -> Ціль: {desired_pos:+.2f}x [{config.RISK_PROFILE}]"
    )

    if LAST_PROCESSED_CANDLE_TS != candle_ts:
        record_snapshot(
            balance=usdt_balance,
            pos_btc=current_btc,
            price=current_price,
            un_pnl=unrealized_pnl_usd,
            action=signal_val
        )

    execute_rebalance(
        target_position=desired_pos,
        current_price=current_price,
        current_atr=current_atr,
        signal_val=signal_val,
        telemetry=telemetry
    )

    LAST_PROCESSED_CANDLE_TS = candle_ts
    del raw_df


def hibernate_until_next_candle(interval_minutes=15):
    """
    Режим глибокої гібернації:
    - Примусово очищує оперативну пам'ять (gc.collect) перед сном.
    - Спить із 0.00% навантаження на CPU рівно до закриття 15m свічки або сигналу WAKEUP_EVENT.
    """
    gc.collect()
    now = time.time()
    candle_sec = interval_minutes * 60
    next_boundary = (int(now // candle_sec) + 1) * candle_sec + 4
    sleep_seconds = max(1.0, next_boundary - now)

    next_time_str = datetime.fromtimestamp(next_boundary, tz=timezone.utc).strftime('%H:%M:%S UTC')
    config.logger.info(f"💤 Гібернація (0% CPU) на {sleep_seconds:.0f} сек до свічки {next_time_str}...")

    woken_early = WAKEUP_EVENT.wait(timeout=sleep_seconds)
    if woken_early:
        WAKEUP_EVENT.clear()
        config.logger.info("⚡ Отримано сигнал миттєвого пробудження (Команда користувача)!")
    return woken_early


if __name__ == "__main__":
    try:
        config.logger.info("🚀 Запуск QuantCore V7.8 Ultra Institutional Pipeline...")

        init_db()
        load_bot_state()
        cleanup_old_data(days_to_keep=90)

        if not os.path.exists(config.MODEL_PATH):
            raise FileNotFoundError(
                f"❌ Файл бойового ансамблю не знайдено: {config.MODEL_PATH}\n"
                f"Покладіть 'quant_core_production.joblib' у папку {config.BASE_DIR}!"
            )

        config.logger.info(f"📦 Завантаження ансамблю QuantCore V7.8 з '{config.MODEL_PATH}'...")
        bundle = joblib.load(config.MODEL_PATH)
        config.logger.info(f"✅ Ансамбль '{bundle.get('architecture', 'QuantCore_V7_8')}' завантажено в RAM!")

        t = threading.Thread(target=telegram_listener, daemon=True)
        t.start()

        safe_send_telegram(
            f"⚡ <b>QuantCore V7.8 Ultra успішно запущено!</b>\n\n"
            f"• Торгова пара: <code>{config.SYMBOL}</code>\n"
            f"• Профіль ризику: <code>{config.RISK_PROFILE} ({config.TIER1_SIZE:.2f}x .. {config.MAX_CONVICTION_SIZE:.2f}x)</code>\n"
            f"• Архітектура: <code>TSMOM + Pullback + Crash-Shield + ML Ensemble</code>\n"
            f"• Режим очікування: <code>Zero-Idle CPU Hibernation</code>"
        )

        try:
            run_trading_step(bundle, force_recalc=True)
        except Exception as init_err:
            config.logger.error(f"Помилка стартового кроку: {init_err}", exc_info=True)

        while True:
            forced = hibernate_until_next_candle(interval_minutes=15)
            try:
                run_trading_step(bundle, force_recalc=forced)
            except Exception as loop_err:
                config.logger.error(f"Помилка ітерації свічки: {loop_err}", exc_info=True)
                safe_send_telegram(
                    f"⚠️ <b>Збій ітерації свічки:</b>\n<code>{loop_err}</code>\n"
                    f"Робота триває штатно."
                )

    except KeyboardInterrupt:
        config.logger.info("🛑 Бот зупинений вручну.")
    except Exception as fatal_error:
        tb = traceback.format_exc()
        config.logger.critical(f"❌ КРИТИЧНИЙ ЗБІЙ ПРОЦЕСУ:\n{tb}")
        safe_send_telegram(
            f"🚨 <b>КРИТИЧНА ПОМИЛКА БОТА!</b>\n"
            f"<code>{fatal_error}</code>\n"
            f"<pre>{tb[-400:]}</pre>"
        )
        raise fatal_error