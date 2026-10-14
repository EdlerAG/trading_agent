import time
from datetime import datetime, timezone
import numpy as np
import ccxt

import config
from exchange import (
    get_exchange,
    get_current_position_status,
    emergency_close_all,
    check_slippage_and_spread,
    check_funding_rate_risk,
    execute_smart_order
)
from telegram_bot import send_telegram_alert, save_bot_state
import database

DAILY_STARTING_BALANCE = None
LAST_RESET_DATE = None


def check_circuit_breaker(total_equity: float):
    """Circuit Breaker: зупиняє торгівлю при денній просадці >= MAX_DAILY_LOSS_PCT."""
    global DAILY_STARTING_BALANCE, LAST_RESET_DATE
    today = datetime.now(timezone.utc).date()

    if LAST_RESET_DATE != today or DAILY_STARTING_BALANCE is None:
        past_daily_pnl = database.get_daily_pnl()
        DAILY_STARTING_BALANCE = total_equity - past_daily_pnl if (total_equity - past_daily_pnl) > 0 else total_equity
        LAST_RESET_DATE = today
        config.logger.info(f"Оновлено базовий денний капітал Circuit Breaker: ${DAILY_STARTING_BALANCE:.2f} USDT")

    if DAILY_STARTING_BALANCE > 0:
        drawdown = (DAILY_STARTING_BALANCE - total_equity) / DAILY_STARTING_BALANCE
        if drawdown >= config.MAX_DAILY_LOSS_PCT and not config.IS_PAUSED:
            config.IS_PAUSED = True
            emergency_close_all()
            save_bot_state()
            alert_msg = (
                f"🛑 <b>CIRCUIT BREAKER АКТИВОВАНО!</b>\n\n"
                f"Сумарна просадка доби: <b>{drawdown:.2%}</b> (ліміт: {config.MAX_DAILY_LOSS_PCT:.0%}).\n"
                f"Усі позиції ліквідовано в USDT, торгівлю поставлено на паузу."
            )
            send_telegram_alert(alert_msg)
            config.logger.warning(alert_msg)


def monitor_breakeven_protection(exchange, current_btc: float, current_price: float, current_atr: float):
    """Переводить страховий біржовий Stop-Loss у БЕЗЗБИТОК після проходження +1.8x ATR."""
    if abs(current_btc) < config.MIN_TRADE_BTC or config.TRADE_ENTRY_PRICE <= 0.0:
        return

    if config.IS_BREAKEVEN_TRIGGERED:
        return

    entry = config.TRADE_ENTRY_PRICE
    be_dist = config.ATR_BREAKEVEN_TRIGGER * current_atr
    should_trigger = False
    raw_be = 0.0
    close_side = 'sell'

    if current_btc > 0 and (current_price - entry) >= be_dist:
        should_trigger = True
        raw_be = entry * (1.0 + config.BREAKEVEN_BUFFER_PCT)
        close_side = 'sell'
    elif current_btc < 0 and (entry - current_price) >= be_dist:
        should_trigger = True
        raw_be = entry * (1.0 - config.BREAKEVEN_BUFFER_PCT)
        close_side = 'buy'

    if should_trigger:
        try:
            be_price = float(exchange.price_to_precision(config.SYMBOL, raw_be))
            pos_amount = float(exchange.amount_to_precision(config.SYMBOL, abs(current_btc)))

            open_orders = exchange.fetch_open_orders(config.SYMBOL)
            for order in open_orders:
                if str(order.get('type')).lower() in ['stop_market', 'stop']:
                    try:
                        exchange.cancel_order(order['id'], config.SYMBOL)
                    except Exception:
                        pass

            exchange.create_order(
                symbol=config.SYMBOL,
                type='STOP_MARKET',
                side=close_side,
                amount=pos_amount,
                price=None,
                params={
                    'stopPrice': be_price,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE'
                }
            )

            config.IS_BREAKEVEN_TRIGGERED = True
            config.ACTIVE_SL_PRICE = be_price
            save_bot_state()
            msg = (
                f"🛡️ <b>Страховий Stop-Loss переведено в БЕЗЗБИТОК!</b>\n\n"
                f"• Позиція: <code>{current_btc:+.3f} BTC</code> | Вхід: <code>${entry:,.1f}</code>\n"
                f"• Новий Stop-Loss: <b>${be_price:,.1f} USDT</b> (Mark Price)\n"
                f"• Покриває ціну входу та біржові комісії. Верхня межа прибутку відкрита!"
            )
            send_telegram_alert(msg)
            config.logger.info(f"Страховий SL успішно перенесено в безубиток (${be_price:.1f}).")
        except Exception as e:
            config.logger.error(f"Помилка оновлення Breakeven ордера: {e}")


def sync_orders_and_position(exchange):
    """Синхронізація біржового стану з локальним станом бота та БД."""
    try:
        current_btc, usdt_balance, entry_price, unrealized_pnl = get_current_position_status(exchange)
        open_orders = exchange.fetch_open_orders(config.SYMBOL)

        if abs(current_btc) < config.MIN_TRADE_BTC:
            if config.TRADE_ENTRY_PRICE > 0.0 or len(open_orders) > 0:
                config.logger.info("Позицію закрито біржею. Очищення ордерів та облік PnL...")
                try:
                    exchange.cancel_all_orders(config.SYMBOL)
                except Exception:
                    pass

                tot_pnl = 0.0
                try:
                    trades = exchange.fetch_my_trades(config.SYMBOL, limit=5)
                    if trades:
                        last_order_id = trades[-1].get('order')
                        related = [t for t in trades if t.get('order') == last_order_id] or [trades[-1]]
                        tot_amount = sum(float(t.get('amount') or 0.0) for t in related)
                        tot_fee = sum(float(t.get('fee', {}).get('cost') or 0.0) for t in related)
                        tot_pnl = sum(float(t.get('info', {}).get('realizedPnl') or 0.0) for t in related)
                        last_side = str(related[-1].get('side', '')).upper()
                        avg_price = float(related[-1].get('price') or 0.0)

                        database.record_trade(
                            side=last_side,
                            amount=tot_amount,
                            price=avg_price,
                            order_id=last_order_id,
                            pnl=tot_pnl,
                            fee=tot_fee,
                            note="STOP_OR_EXCHANGE_EXIT"
                        )
                except Exception as db_err:
                    config.logger.warning(f"Не вдалося оновити історію закритої угоди в БД: {db_err}")

                send_telegram_alert(
                    f"🛡️ <b>Захисний вихід виконано біржею!</b>\n"
                    f"• Реалізований PnL: <b>${tot_pnl:+.2f} USDT</b>\n"
                    f"• Вільний баланс: <b>${usdt_balance:,.2f} USDT</b>"
                )

            config.TRADE_ENTRY_PRICE = 0.0
            config.TRADE_CANDLES_COUNT = 0
            config.IS_BREAKEVEN_TRIGGERED = False
            config.IS_TP1_TRIGGERED = False
            config.INITIAL_TRADE_AMOUNT = 0.0
            config.ACTIVE_SL_PRICE = 0.0
            save_bot_state()
        else:
            if config.TRADE_ENTRY_PRICE == 0.0 and entry_price > 0:
                config.TRADE_ENTRY_PRICE = entry_price
            if getattr(config, 'INITIAL_TRADE_AMOUNT', 0.0) == 0.0:
                config.INITIAL_TRADE_AMOUNT = abs(current_btc)

        return current_btc, usdt_balance, entry_price, unrealized_pnl

    except Exception as e:
        config.logger.error(f"Помилка синхронізації: {e}")
        return 0.0, 0.0, 0.0, 0.0


def execute_rebalance(target_position: float, current_price: float, current_atr: float,
                      signal_val: float = 0.0, telemetry: dict = None):
    """
    Виконавчий модуль QuantCore V7.8 Ultra:
    - підтримує цільову позицію від 0.0x до 1.50x (згідно з RISK_PROFILE)
    - фільтрує дрібні зміни через ACTION_DEADZONE (0.25)
    - виставляє страховий катастрофічний Stop-Loss (3.5x ATR) та переводить його в Breakeven
    """
    exchange = get_exchange()

    try:
        if config.IS_PAUSED:
            if config.PAUSE_UNTIL and datetime.now(timezone.utc) > config.PAUSE_UNTIL:
                config.IS_PAUSED = False
                config.PAUSE_UNTIL = None
                save_bot_state(telemetry)
                send_telegram_alert("🟢 <b>Торгівлю автоматично відновлено після завершення паузи!</b>")
            else:
                save_bot_state(telemetry)
                return

        current_btc, usdt_balance, entry_p, un_pnl = sync_orders_and_position(exchange)
        total_equity = max(0.0, usdt_balance + un_pnl)
        check_circuit_breaker(total_equity)

        if total_equity < 10.0 or config.IS_PAUSED:
            save_bot_state(telemetry)
            return

        if abs(current_btc) >= config.MIN_TRADE_BTC:
            config.TRADE_CANDLES_COUNT += 1

        monitor_breakeven_protection(exchange, current_btc, current_price, current_atr)
        save_bot_state(telemetry)

        current_pos_norm = (current_btc * current_price) / total_equity if total_equity > 0 else 0.0

        is_closing_to_cash = abs(target_position) < config.CASH_ZONE_THRESHOLD
        is_opening_from_cash = abs(current_pos_norm) < config.CASH_ZONE_THRESHOLD and abs(target_position) >= config.CASH_ZONE_THRESHOLD
        is_flip = (current_pos_norm * target_position) < 0.0
        action_diff = abs(target_position - current_pos_norm)

        if not (is_closing_to_cash or is_opening_from_cash or is_flip) and action_diff < config.ACTION_DEADZONE:
            config.logger.info(
                f"Дельта експозиції {action_diff:.2f} < DEADZONE ({config.ACTION_DEADZONE}). "
                f"Утримання позиції {current_pos_norm:+.2f}x (Сигнал: {signal_val:+.3f})."
            )
            return

        target_usdt = total_equity * target_position
        target_btc_raw = target_usdt / current_price
        target_btc = float(exchange.amount_to_precision(config.SYMBOL, abs(target_btc_raw)))
        if target_position < 0:
            target_btc = -target_btc

        diff_btc = target_btc - current_btc
        min_trade = config.MIN_TRADE_BTC

        if is_closing_to_cash:
            if abs(current_btc) >= min_trade:
                diff_btc = -current_btc
                target_btc = 0.0
            else:
                return
        elif abs(diff_btc) < min_trade:
            return

        planned_side = 'buy' if diff_btc > 0 else 'sell'

        # Slippage Guard (один запит стакану — котирування передаємо далі!)
        is_spread_ok, spread_pct, best_bid, best_ask = check_slippage_and_spread()
        if not is_spread_ok and not is_closing_to_cash:
            send_telegram_alert(f"⚠️ Вхід відкладено: спред {spread_pct*100:.3f}% перевищує ліміт.")
            return

        # Funding Guard (тільки при відкритті/доборі)
        if not is_closing_to_cash:
            is_funding_risky, fund_rate = check_funding_rate_risk()
            if is_funding_risky:
                harmful = (planned_side == 'buy' and fund_rate > 0) or (planned_side == 'sell' and fund_rate < 0)
                if harmful:
                    send_telegram_alert(f"⚠️ Вхід відкладено: високий Funding Rate ({fund_rate*100:.4f}%).")
                    return

        try:
            exchange.cancel_all_orders(config.SYMBOL)
        except Exception:
            pass

        realized_pnl_est = 0.0
        note_label = f"QuantCore Entry ({target_position:+.2f}x)"
        if is_closing_to_cash:
            realized_pnl_est = un_pnl
            note_label = "Exit to Cash (100% USDT)"
        elif abs(target_btc) > abs(current_btc) and abs(current_btc) >= min_trade:
            note_label = f"Conviction Dip-Boost ({target_position:+.2f}x)"

        order_res = execute_smart_order(
            diff_btc,
            realized_pnl_est=realized_pnl_est,
            note=note_label,
            best_bid=best_bid,
            best_ask=best_ask
        )
        if not order_res:
            return

        time.sleep(0.8)
        new_btc, new_bal, real_entry_price, new_un_pnl = get_current_position_status(exchange)
        exec_price = real_entry_price if real_entry_price > 0 else order_res['price']

        if abs(new_btc) >= min_trade:
            if is_opening_from_cash or is_flip:
                config.TRADE_ENTRY_PRICE = exec_price
                config.TRADE_CANDLES_COUNT = 1
                config.IS_BREAKEVEN_TRIGGERED = False
                config.IS_TP1_TRIGGERED = False
                config.INITIAL_TRADE_AMOUNT = abs(new_btc)
            else:
                config.TRADE_ENTRY_PRICE = exec_price

            total_amount = float(exchange.amount_to_precision(config.SYMBOL, abs(new_btc)))
            sl_mult = getattr(config, "EMERGENCY_SL_ATR_MULT", 3.5)
            sl_dist = sl_mult * current_atr

            if new_btc > 0:
                raw_sl = (exec_price * (1.0 + config.BREAKEVEN_BUFFER_PCT)) if config.IS_BREAKEVEN_TRIGGERED else (exec_price - sl_dist)
                close_side = 'sell'
            else:
                raw_sl = (exec_price * (1.0 - config.BREAKEVEN_BUFFER_PCT)) if config.IS_BREAKEVEN_TRIGGERED else (exec_price + sl_dist)
                close_side = 'buy'

            sl_price = float(exchange.price_to_precision(config.SYMBOL, raw_sl))
            config.ACTIVE_SL_PRICE = sl_price
            save_bot_state(telemetry)

            try:
                exchange.create_order(
                    symbol=config.SYMBOL,
                    type='STOP_MARKET',
                    side=close_side,
                    amount=total_amount,
                    price=None,
                    params={
                        'stopPrice': sl_price,
                        'reduceOnly': True,
                        'workingType': 'MARK_PRICE'
                    }
                )
            except Exception as sl_err:
                config.logger.warning(f"Не вдалося виставити страховий SL: {sl_err}")

            icon = "🟢" if new_btc > 0 else "🔴"
            msg = (
                f"⚡ <b>QuantCore V7.8 Ultra: Ордер виконано!</b>\n"
                f"═══════════════════════\n"
                f"• <b>Операція:</b> {note_label}\n"
                f"• <b>Напрямок:</b> {planned_side.upper()} {icon} (<code>{order_res['amount']} BTC</code>)\n"
                f"• <b>Експозиція:</b> <b>{target_position:+.2f}x</b> (Разом: <code>{new_btc:+.3f} BTC</code>)\n"
                f"• <b>Сигнал ядра:</b> <code>{signal_val:+.3f}</code> (Поріг: <code>+{config.ENTER_LONG_TH:.2f}</code>)\n"
                f"• <b>Середня ціна входу:</b> <code>${exec_price:,.1f}</code>\n"
                f"• <b>🛡️ Страховий SL:</b> <code>${sl_price:,.1f}</code> (Mark Price)\n"
                f"• <b>Сумарний Equity:</b> <b>${total_equity:,.2f} USDT</b>"
            )
            send_telegram_alert(msg)

        else:
            config.TRADE_ENTRY_PRICE = 0.0
            config.TRADE_CANDLES_COUNT = 0
            config.IS_BREAKEVEN_TRIGGERED = False
            config.IS_TP1_TRIGGERED = False
            config.INITIAL_TRADE_AMOUNT = 0.0
            config.ACTIVE_SL_PRICE = 0.0
            save_bot_state(telemetry)
            send_telegram_alert(
                f"⚪ <b>QuantCore V7.8 Ultra: Вихід у 100% КЕШ (USDT)!</b>\n"
                f"═══════════════════════\n"
                f"• <b>Фіксований PnL угоди:</b> <b>${realized_pnl_est:+.2f} USDT</b>\n"
                f"• <b>Сигнал виходу:</b> <code>{signal_val:+.3f}</code>\n"
                f"• <b>Новий баланс:</b> <b>${new_bal:,.2f} USDT</b>"
            )

    except Exception as e:
        config.logger.error(f"Помилка ребалансування: {e}", exc_info=True)
        send_telegram_alert(f"❌ <b>Помилка виконання ордера:</b>\n<code>{e}</code>")