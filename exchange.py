import time
import ccxt
import pandas as pd
import numpy as np
import config
import database

_EXCHANGE_INSTANCE = None
_CANDLES_CACHE_DF = None


def get_exchange():
    """Singleton-клієнт CCXT з налаштуванням One-Way Mode та Leverage 2x"""
    global _EXCHANGE_INSTANCE
    if _EXCHANGE_INSTANCE is None:
        try:
            exchange = ccxt.binance({
                'apiKey': config.TESTNET_API_KEY,
                'secret': config.TESTNET_SECRET_KEY,
                'enableRateLimit': True,
                'timeout': 15000,
                'options': {
                    'defaultType': 'future',
                    'adjustForTimeDifference': True
                }
            })
            exchange.enable_demo_trading(True)
            exchange.load_markets()

            try:
                exchange.set_position_mode(hedged=False, symbol=config.SYMBOL)
            except Exception:
                pass

            try:
                lev = getattr(config, "EXCHANGE_LEVERAGE", 2)
                exchange.set_leverage(lev, symbol=config.SYMBOL)
            except Exception:
                pass

            _EXCHANGE_INSTANCE = exchange
            config.logger.info(f"✅ Підключення до Binance Futures встановлено (One-Way Mode, Leverage {getattr(config, 'EXCHANGE_LEVERAGE', 2)}x).")
        except Exception as e:
            config.logger.error(f"❌ Фатальна помилка ініціалізації CCXT: {e}")
            raise
    return _EXCHANGE_INSTANCE


def get_current_position_status(exchange=None):
    """Повертає актуальний біржовий стан: (current_btc, usdt_balance, entry_price, unrealized_pnl)"""
    if exchange is None:
        exchange = get_exchange()

    try:
        balance = exchange.fetch_balance()
        usdt_balance = float(balance.get('total', {}).get('USDT') or balance.get('free', {}).get('USDT') or 0.0)

        positions = exchange.fetch_positions([config.SYMBOL])

        current_btc = 0.0
        entry_price = 0.0
        unrealized_pnl = 0.0

        for p in positions:
            if p.get('symbol') == config.SYMBOL:
                contracts = float(p.get('contracts') or 0.0)
                side = str(p.get('side') or '').lower()
                entry_price = float(p.get('entryPrice') or 0.0)
                unrealized_pnl = float(p.get('unrealizedPnl') or 0.0)

                if side == 'long':
                    current_btc = contracts
                elif side == 'short':
                    current_btc = -contracts
                break

        return current_btc, usdt_balance, entry_price, unrealized_pnl

    except Exception as e:
        config.logger.error(f"Помилка отримання статусу позиції: {e}")
        return 0.0, 0.0, 0.0, 0.0


def _klines_to_df(raw_klines: list) -> pd.DataFrame:
    rows = [{
        'open_ms': int(k[0]),
        'open': float(k[1]),
        'high': float(k[2]),
        'low': float(k[3]),
        'close': float(k[4]),
        'volume': float(k[5]),
        'taker_base': float(k[9])
    } for k in raw_klines]
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=['open_ms']).sort_values('open_ms').reset_index(drop=True)

    now_ms = time.time() * 1000
    candle_ms = 15 * 60 * 1000
    if not df.empty and now_ms < (int(df['open_ms'].iloc[-1]) + candle_ms):
        df = df.iloc[:-1].reset_index(drop=True)

    df['timestamp'] = pd.to_datetime(df['open_ms'], unit='ms')
    return df


def fetch_historical_candles(limit=None):
    """
    Інтелектуальне завантаження свічок із In-Memory Ring-Buffer кешем:
    - Перший запуск стягує 2,600 свічок.
    - Кожна наступна свічка довантажує лише дельту (5–10 барів за 0.04 сек!).
    """
    global _CANDLES_CACHE_DF
    exchange = get_exchange()
    target_limit = limit or config.CANDLES_FETCH_LIMIT
    candle_ms = 15 * 60 * 1000

    try:
        if _CANDLES_CACHE_DF is not None and len(_CANDLES_CACHE_DF) >= (target_limit - 10):
            last_cached_ms = int(_CANDLES_CACHE_DF['open_ms'].iloc[-1])
            now_ms = int(time.time() * 1000)
            missing_bars = int((now_ms - last_cached_ms) // candle_ms) + 3

            if 1 <= missing_bars <= 120:
                params = {
                    'symbol': config.BINANCE_PAIR,
                    'interval': '15m',
                    'limit': min(150, missing_bars + 5)
                }
                raw_tail = exchange.fapiPublicGetKlines(params)
                if raw_tail:
                    tail_df = _klines_to_df(raw_tail)
                    combined = pd.concat([_CANDLES_CACHE_DF, tail_df], ignore_index=True)
                    combined = combined.drop_duplicates(subset=['open_ms'], keep='last').sort_values('open_ms').reset_index(drop=True)
                    if len(combined) > target_limit:
                        combined = combined.iloc[-target_limit:].reset_index(drop=True)
                    _CANDLES_CACHE_DF = combined
                    return _CANDLES_CACHE_DF.copy()

        all_klines = []
        end_time_ms = int(time.time() * 1000)

        while len(all_klines) < (target_limit + 5):
            batch_size = min(1500, (target_limit + 5) - len(all_klines))
            params = {
                'symbol': config.BINANCE_PAIR,
                'interval': '15m',
                'limit': batch_size,
                'endTime': end_time_ms
            }
            raw_batch = exchange.fapiPublicGetKlines(params)
            if not raw_batch:
                break

            all_klines = raw_batch + all_klines
            first_open_ms = int(raw_batch[0][0])
            end_time_ms = first_open_ms - 1

            if len(raw_batch) < batch_size:
                break

        if not all_klines:
            return None

        df = _klines_to_df(all_klines)
        if len(df) > target_limit:
            df = df.iloc[-target_limit:].reset_index(drop=True)

        _CANDLES_CACHE_DF = df
        return _CANDLES_CACHE_DF.copy()

    except Exception as e:
        config.logger.error(f"Помилка завантаження свічок з біржі: {e}")
        return _CANDLES_CACHE_DF.copy() if _CANDLES_CACHE_DF is not None else None


def check_slippage_and_spread():
    """Повертає (is_safe, spread_pct, best_bid, best_ask)"""
    exchange = get_exchange()
    try:
        orderbook = exchange.fetch_order_book(config.SYMBOL, limit=5)
        best_bid = float(orderbook['bids'][0][0]) if orderbook['bids'] else 0.0
        best_ask = float(orderbook['asks'][0][0]) if orderbook['asks'] else 0.0

        if best_bid <= 0 or best_ask <= 0:
            return False, 0.0, 0.0, 0.0

        spread_pct = (best_ask - best_bid) / best_bid
        is_safe = spread_pct <= config.MAX_ALLOWED_SPREAD_PCT

        if not is_safe:
            config.logger.warning(f"⚠️ Slippage Guard! Спред {spread_pct*100:.3f}% > {config.MAX_ALLOWED_SPREAD_PCT*100:.3f}%")

        return is_safe, spread_pct, best_bid, best_ask

    except Exception as e:
        config.logger.error(f"Помилка перевірки спреду: {e}")
        return False, 0.0, 0.0, 0.0


def check_funding_rate_risk():
    exchange = get_exchange()
    try:
        funding_info = exchange.fetch_funding_rate(config.SYMBOL)
        rate = float(funding_info.get('fundingRate') or 0.0)
        next_funding_time = funding_info.get('fundingTimestamp')

        if not next_funding_time:
            return False, rate

        time_to_funding_min = (next_funding_time - (time.time() * 1000)) / (1000 * 60)

        if 0 < time_to_funding_min <= config.FUNDING_BUFFER_MINUTES:
            if abs(rate) >= config.MAX_FUNDING_RATE:
                return True, rate

        return False, rate

    except Exception as e:
        config.logger.error(f"Помилка перевірки funding rate: {e}")
        return False, 0.0


def execute_smart_order(target_delta_btc: float, realized_pnl_est: float = 0.0,
                        note: str = "", best_bid: float = 0.0, best_ask: float = 0.0):
    """
    Виконання ордера без повторного мережевого запиту стакану (якщо вже передано best_bid/best_ask).
    """
    exchange = get_exchange()
    side = 'buy' if target_delta_btc > 0 else 'sell'
    raw_amount = abs(target_delta_btc)

    try:
        amount = float(exchange.amount_to_precision(config.SYMBOL, raw_amount))

        if amount < config.MIN_TRADE_BTC:
            config.logger.info(f"Пропуск: об'єм {amount} BTC < MIN_TRADE_BTC ({config.MIN_TRADE_BTC})")
            return None

        if best_bid <= 0 or best_ask <= 0:
            orderbook = exchange.fetch_order_book(config.SYMBOL, limit=5)
            best_bid = float(orderbook['bids'][0][0])
            best_ask = float(orderbook['asks'][0][0])

        price_estimate = best_ask if side == 'buy' else best_bid
        notional_value = amount * price_estimate
        if notional_value < 5.0:
            config.logger.warning(f"Пропуск: номінал ордера ${notional_value:.2f} < 5.0 USDT")
            return None

        limit_price = best_bid if side == 'buy' else best_ask
        limit_price_str = exchange.price_to_precision(config.SYMBOL, limit_price)

        config.logger.info(f"⏳ Розміщення Maker-ордера: {side.upper()} {amount} BTC @ ${limit_price_str}...")

        try:
            maker_order = exchange.create_order(
                symbol=config.SYMBOL,
                type='limit',
                side=side,
                amount=amount,
                price=float(limit_price_str),
                params={'postOnly': True}
            )
        except Exception as pe:
            config.logger.warning(f"Post-Only відхилено ({pe}), перехід на Market-ордер.")
            maker_order = None

        filled = False
        fill_price = 0.0
        fee_cost = 0.0
        order_id = None

        if maker_order and 'id' in maker_order:
            order_id = maker_order['id']
            start_wait = time.time()
            while time.time() - start_wait < config.MAKER_TIMEOUT_SEC:
                time.sleep(1.5)
                check_o = exchange.fetch_order(order_id, config.SYMBOL)
                if check_o.get('status') == 'closed':
                    filled = True
                    fill_price = float(check_o.get('average') or limit_price)
                    fee_cost = float(check_o.get('fee', {}).get('cost') or (amount * fill_price * 0.0002))
                    config.logger.info(f"⚡ Maker-ордер виконано за ціною ${fill_price:.2f}!")
                    break

            if not filled:
                config.logger.info(f"Таймаут Maker ({config.MAKER_TIMEOUT_SEC}с). Перехід на Market...")
                try:
                    exchange.cancel_order(order_id, config.SYMBOL)
                except Exception:
                    pass

        if not filled:
            remaining_amount = amount
            if order_id:
                try:
                    canceled_o = exchange.fetch_order(order_id, config.SYMBOL)
                    filled_qty = float(canceled_o.get('filled') or 0.0)
                    remaining_amount = max(0.0, amount - filled_qty)
                except Exception:
                    pass

            if remaining_amount >= config.MIN_TRADE_BTC:
                market_amount = float(exchange.amount_to_precision(config.SYMBOL, remaining_amount))
                m_order = exchange.create_market_order(config.SYMBOL, side, market_amount)
                fill_price = float(m_order.get('average') or m_order.get('price') or price_estimate)
                fee_cost += float(m_order.get('fee', {}).get('cost') or (market_amount * fill_price * 0.0005))
                order_id = m_order.get('id')
                config.logger.info(f"✅ Market-ордер виконано: {side.upper()} {market_amount} BTC @ ${fill_price:.2f}")

        database.record_trade(
            side=side,
            amount=amount,
            price=fill_price,
            order_id=order_id,
            pnl=realized_pnl_est,
            fee=fee_cost,
            note=note
        )

        return {
            'side': side,
            'amount': amount,
            'price': fill_price,
            'fee': fee_cost,
            'order_id': order_id
        }

    except Exception as e:
        config.logger.error(f"❌ Критична помилка виконання ордера: {e}")
        return None


def emergency_close_all():
    exchange = get_exchange()
    try:
        exchange.cancel_all_orders(config.SYMBOL)
        current_btc, usdt_balance, entry_p, un_pnl = get_current_position_status(exchange)

        config.TRADE_ENTRY_PRICE = 0.0
        config.TRADE_CANDLES_COUNT = 0
        config.IS_BREAKEVEN_TRIGGERED = False
        config.IS_TP1_TRIGGERED = False
        config.INITIAL_TRADE_AMOUNT = 0.0
        config.ACTIVE_SL_PRICE = 0.0

        if abs(current_btc) >= config.MIN_TRADE_BTC:
            side = 'sell' if current_btc > 0 else 'buy'
            amount_formatted = float(exchange.amount_to_precision(config.SYMBOL, abs(current_btc)))

            order = exchange.create_market_order(
                config.SYMBOL,
                side,
                amount_formatted,
                params={'reduceOnly': True}
            )

            fill_price = float(order.get('average') or order.get('price') or 0.0)
            fee_cost = float(order.get('fee', {}).get('cost') or (amount_formatted * fill_price * 0.0005))

            database.record_trade(
                side=side,
                amount=amount_formatted,
                price=fill_price,
                order_id=order.get('id'),
                pnl=un_pnl,
                fee=fee_cost,
                note="EMERGENCY_CLOSE"
            )

            msg = (
                f"🚨 <b>Аварійне закриття виконано!</b>\n"
                f"Закрито: {amount_formatted} BTC ({side.upper()})\n"
                f"Ціна закриття: ~${fill_price:,.2f}\n"
                f"Фіксований PnL: ${un_pnl:+.2f}\n"
                f"Баланс: {usdt_balance:,.2f} USDT"
            )
            config.logger.info(msg.replace("<b>", "").replace("</b>", ""))
            return msg
        else:
            return "ℹ️ Відкритих позицій немає (100% у кеші USDT)."

    except Exception as e:
        config.logger.error(f"Помилка аварійного закриття: {e}")
        return f"❌ Помилка аварійного закриття: {e}"