import time
import asyncio
import logging
from typing import Dict, Optional, Tuple, Any, List
import ccxt
import pandas as pd

from app.core.config import settings, symbol_to_ccxt, ccxt_to_symbol
from app.domain.interfaces import IExchangeGateway
from app.domain.schemas import ExchangePositionDTO, OrderExecutionDTO
from app.services.database_service import DatabaseService


class ExchangeCcxtService(IExchangeGateway):
    """
    Мультивалютний клієнт Binance Futures (One-Way Mode) з:
    - In-Memory Ring-Buffer кешем свічок для 5+ монет.
    - Автоматичним обліком закритих біржею Stop-Loss ордерів у SQLite.
    """

    __slots__ = ("_logger", "_db", "_exchange", "_candles_cache")

    def __init__(self, logger: logging.Logger, db_service: DatabaseService) -> None:
        self._logger = logger
        self._db = db_service
        self._exchange: Optional[ccxt.binance] = None
        self._candles_cache: Dict[str, pd.DataFrame] = {}

    @property
    def name(self) -> str:
        return "ExchangeCcxtService"

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        if not settings.BINANCE_API_KEY or not settings.BINANCE_SECRET_KEY:
            self._logger.warning("⚠️ Ключі Binance API не задано. Шлюз працює у режимі читання свічок.")
        ex = ccxt.binance({
            "apiKey": settings.BINANCE_API_KEY,
            "secret": settings.BINANCE_SECRET_KEY,
            "enableRateLimit": True,
            "timeout": 15000,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
            },
        })
        if settings.USE_DEMO_TRADING:
            ex.enable_demo_trading(True)

        ex.load_markets()
        self._exchange = ex

        if settings.BINANCE_API_KEY:
            try:
                ex.set_position_mode(hedged=False)
            except Exception:
                pass
            for sym in settings.DEFAULT_SYMBOLS:
                try:
                    ex.set_leverage(settings.EXCHANGE_LEVERAGE, symbol=symbol_to_ccxt(sym))
                except Exception:
                    pass

        self._logger.info(
            f"✅ Шлюз Binance Futures готовий (Demo={settings.USE_DEMO_TRADING}, Плече={settings.EXCHANGE_LEVERAGE}x)."
        )

    async def shutdown(self) -> None:
        self._candles_cache.clear()
        if self._exchange is not None and hasattr(self._exchange, "close"):
            try:
                if asyncio.iscoroutinefunction(self._exchange.close):
                    await self._exchange.close()
                else:
                    self._exchange.close()
            except Exception:
                pass

    def safe_amount(self, symbol: str, raw_qty: float) -> float:
        qty = abs(float(raw_qty))
        min_qty, step_size, _, _, _ = settings.get_symbol_spec(symbol)
        if qty < min(min_qty * 0.5, step_size):
            return 0.0
        ccxt_sym = symbol_to_ccxt(symbol)
        try:
            if self._exchange is not None:
                return float(self._exchange.amount_to_precision(ccxt_sym, qty))
        except Exception:
            pass
        steps = round(qty / step_size)
        return round(steps * step_size, 6)

    def safe_price(self, symbol: str, raw_price: float) -> float:
        p = float(raw_price)
        if p <= 0.0:
            return 0.0
        ccxt_sym = symbol_to_ccxt(symbol)
        try:
            if self._exchange is not None:
                return float(self._exchange.price_to_precision(ccxt_sym, p))
        except Exception:
            pass
        return round(p, 4 if p < 10.0 else 2)

    async def sync_exchange_stop_closure(self, symbol: str) -> Optional[Tuple[float, float, float]]:
        """
        Викликається, коли відкрита позиція зникла на біржі (спрацював STOP_MARKET).
        Скасовує залишкові ордери, записує фактичний PnL у БД і повертає (qty, avg_price, realized_pnl).
        """
        return await asyncio.to_thread(self._sync_exchange_stop_closure_sync, symbol)

    def _sync_exchange_stop_closure_sync(self, symbol: str) -> Optional[Tuple[float, float, float]]:
        if self._exchange is None:
            return None
        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        try:
            self._exchange.cancel_all_orders(ccxt_sym)
        except Exception:
            pass
        try:
            trades = self._exchange.fetch_my_trades(ccxt_sym, limit=6)
            if not trades:
                return None
            last_order_id = trades[-1].get("order")
            related = [t for t in trades if t.get("order") == last_order_id] or [trades[-1]]
            tot_qty = sum(float(t.get("amount") or 0.0) for t in related if isinstance(t, dict))
            tot_fee = sum(float((t.get("fee") or {}).get("cost") or 0.0) for t in related if isinstance(t, dict))
            tot_pnl = sum(float((t.get("info") or {}).get("realizedPnl") or 0.0) for t in related if isinstance(t, dict))
            last_side = str(related[-1].get("side") or "SELL").upper()
            avg_price = float(related[-1].get("price") or 0.0)

            self._db.record_trade(
                symbol=clean_sym,
                side=last_side,
                amount=tot_qty,
                price=avg_price,
                order_id=str(last_order_id or ""),
                pnl=tot_pnl,
                fee=tot_fee,
                note="MFE_HARVESTER_TP" if tot_pnl >= 0.0 else "STOP_LOSS_EXCHANGE",
            )
            return tot_qty, avg_price, tot_pnl
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean_sym}] Не вдалося зчитати деталі закритого стопа: {e}")
            return None

    async def fetch_account_snapshot(
        self, symbols: Tuple[str, ...]
    ) -> Tuple[float, float, Dict[str, ExchangePositionDTO], bool]:
        return await asyncio.to_thread(self._fetch_account_snapshot_sync, symbols)

    def _fetch_account_snapshot_sync(
        self, symbols: Tuple[str, ...]
    ) -> Tuple[float, float, Dict[str, ExchangePositionDTO], bool]:
        if self._exchange is None or not settings.BINANCE_API_KEY:
            return 0.0, 0.0, {}, False
        try:
            bal = self._exchange.fetch_balance()
            usdt_wallet = float(
                (bal.get("total") or {}).get("USDT")
                or (bal.get("free") or {}).get("USDT")
                or 0.0
            )
            ccxt_syms = [symbol_to_ccxt(s) for s in symbols]
            raw_positions = self._exchange.fetch_positions(ccxt_syms)

            pos_map: Dict[str, ExchangePositionDTO] = {
                s.upper(): ExchangePositionDTO(symbol=s.upper()) for s in symbols
            }
            total_upnl = 0.0

            for p in raw_positions:
                c_sym = str(p.get("symbol") or "")
                clean_sym = ccxt_to_symbol(c_sym)
                if clean_sym not in pos_map:
                    continue
                contracts = float(p.get("contracts") or 0.0)
                side = str(p.get("side") or "").lower()
                entry_p = float(p.get("entryPrice") or 0.0)
                mark_p = float(p.get("markPrice") or entry_p or 0.0)
                upnl = float(p.get("unrealizedPnl") or 0.0)

                signed_qty = contracts if side == "long" else (-contracts if side == "short" else 0.0)
                total_upnl += upnl
                pos_map[clean_sym] = ExchangePositionDTO(
                    symbol=clean_sym,
                    contracts_qty=signed_qty,
                    entry_price=entry_p,
                    mark_price=mark_p,
                    unrealized_pnl=upnl,
                    notional_usdt=abs(signed_qty) * mark_p,
                )

            return usdt_wallet, total_upnl, pos_map, True
        except Exception as e:
            self._logger.error(f"Помилка зчитування балансу/позицій з біржі: {e}")
            return 0.0, 0.0, {}, False

    @staticmethod
    def _klines_to_df(raw_klines: list) -> pd.DataFrame:
        rows = [
            {
                "open_ms": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "taker_base": float(k[9]),
            }
            for k in raw_klines
        ]
        df = pd.DataFrame(rows).drop_duplicates(subset=["open_ms"]).sort_values("open_ms").reset_index(drop=True)
        now_ms = time.time() * 1000.0
        candle_ms = 15 * 60 * 1000
        if not df.empty and now_ms < (int(df["open_ms"].iloc[-1]) + candle_ms):
            df = df.iloc[:-1].reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["open_ms"], unit="ms")
        return df

    async def fetch_funding_rates(self, symbols: Tuple[str, ...]) -> Dict[str, float]:
        return await asyncio.to_thread(self._fetch_funding_rates_sync, symbols)

    def _fetch_funding_rates_sync(self, symbols: Tuple[str, ...]) -> Dict[str, float]:
        if self._exchange is None:
            return {}
        try:
            ccxt_syms = [symbol_to_ccxt(s) for s in symbols]
            raw_fr = self._exchange.fetch_funding_rates(ccxt_syms)
            rates: Dict[str, float] = {}
            for s in symbols:
                c_sym = symbol_to_ccxt(s)
                item = raw_fr.get(c_sym) or raw_fr.get(s) or {}
                rates[s.upper()] = float(item.get("fundingRate") or 0.0)
            return rates
        except Exception:
            return {}

    async def fetch_delta_candles(self, symbol: str, limit: int = settings.CANDLES_FETCH_LIMIT) -> Optional[pd.DataFrame]:
        return await asyncio.to_thread(self._fetch_delta_candles_sync, symbol, limit)

    def _fetch_delta_candles_sync(self, symbol: str, target_limit: int) -> Optional[pd.DataFrame]:
        if self._exchange is None:
            return None
        clean_sym = ccxt_to_symbol(symbol)
        candle_ms = 15 * 60 * 1000
        cached_df = self._candles_cache.get(clean_sym)

        try:
            if cached_df is not None and len(cached_df) >= (target_limit - 15):
                if "open_ms" in cached_df.columns:
                    last_ms = int(cached_df["open_ms"].iloc[-1])
                elif "timestamp" in cached_df.columns:
                    last_ms = int(pd.to_datetime(cached_df["timestamp"]).iloc[-1].timestamp() * 1000)
                else:
                    last_ms = int(time.time() * 1000) - (len(cached_df) * candle_ms)
                now_ms = int(time.time() * 1000)
                missing_bars = int((now_ms - last_ms) // candle_ms) + 3
                if 1 <= missing_bars <= 100:
                    raw_tail = self._exchange.fapiPublicGetKlines({
                        "symbol": clean_sym,
                        "interval": "15m",
                        "limit": min(120, missing_bars + 4),
                    })
                    if raw_tail:
                        tail_df = self._klines_to_df(raw_tail)
                        comb = pd.concat([cached_df, tail_df], ignore_index=True)
                        comb = comb.drop_duplicates(subset=["open_ms"], keep="last").sort_values("open_ms").reset_index(drop=True)
                        if len(comb) > target_limit:
                            comb = comb.iloc[-target_limit:].reset_index(drop=True)
                        self._candles_cache[clean_sym] = comb
                        return comb

            all_klines = []
            end_ms = int(time.time() * 1000)
            while len(all_klines) < (target_limit + 5):
                batch_sz = min(1500, (target_limit + 5) - len(all_klines))
                raw_b = self._exchange.fapiPublicGetKlines({
                    "symbol": clean_sym,
                    "interval": "15m",
                    "limit": batch_sz,
                    "endTime": end_ms,
                })
                if not raw_b:
                    break
                all_klines = raw_b + all_klines
                end_ms = int(raw_b[0][0]) - 1
                if len(raw_b) < batch_sz:
                    break

            if not all_klines:
                return cached_df

            df = self._klines_to_df(all_klines)
            if len(df) > target_limit:
                df = df.iloc[-target_limit:].reset_index(drop=True)
            self._candles_cache[clean_sym] = df
            return df
        except Exception as e:
            self._logger.error(f"Помилка завантаження свічок {clean_sym}: {e}")
            return cached_df

    async def execute_smart_rebalance_order(
        self,
        symbol: str,
        delta_qty: float,
        mark_price: float,
        realized_pnl_est: float = 0.0,
        note: str = "",
        reduce_only: bool = False,
    ) -> Optional[OrderExecutionDTO]:
        return await asyncio.to_thread(
            self._execute_smart_order_sync, symbol, delta_qty, mark_price, realized_pnl_est, note, reduce_only
        )

    def _execute_smart_order_sync(
        self,
        symbol: str,
        delta_qty: float,
        mark_price: float,
        realized_pnl_est: float,
        note: str,
        reduce_only: bool,
    ) -> Optional[OrderExecutionDTO]:
        if self._exchange is None:
            return None

        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        side = "buy" if delta_qty > 0 else "sell"
        min_qty, _, min_notional, _, _ = settings.get_symbol_spec(clean_sym)

        amount = self.safe_amount(clean_sym, abs(delta_qty))
        if amount < min_qty:
            return None

        try:
            # 1. Глибина стакана та перевірка спреду (limit=20)
            ob = self._exchange.fetch_order_book(ccxt_sym, limit=20)
            bids = ob.get("bids") or []
            asks = ob.get("asks") or []
            best_bid = float(bids[0][0]) if bids else mark_price
            best_ask = float(asks[0][0]) if asks else mark_price
            spread_pct = (best_ask - best_bid) / max(1e-8, best_bid)

            if not reduce_only and spread_pct > settings.MAX_ALLOWED_SPREAD_PCT:
                self._logger.warning(f"⚠️ [{clean_sym}] Спред {spread_pct*100:.3f}% перевищує ліміт. Пропуск входу.")
                return None

            est_price = best_ask if side == "buy" else best_bid
            if (amount * est_price) < min_notional and not reduce_only:
                return None

            # 2. Перевірка 30% ліквідності перших 3 рівнів стакана (TWAP-lite)
            target_depth = asks[:3] if side == "buy" else bids[:3]
            top3_liquidity = sum(float(lvl[1]) for lvl in target_depth if len(lvl) >= 2)

            tranches = [amount]
            if top3_liquidity > 0 and amount > (0.30 * top3_liquidity):
                t1 = self.safe_amount(clean_sym, amount * 0.5)
                t2 = self.safe_amount(clean_sym, amount - t1)
                if t1 >= min_qty and t2 >= min_qty:
                    tranches = [t1, t2]
                    self._logger.info(
                        f"📊 [{clean_sym}] TWAP-lite: обсяг {amount} > 30% топ-3 стакана ({top3_liquidity:.2f}). "
                        f"Розбито на 2 транші: {t1} та {t2} (інтервал 2с)."
                    )

            total_maker_filled = 0.0
            total_market_filled = 0.0
            total_cost = 0.0
            total_fee = 0.0
            last_order_id = ""

            for t_idx, tranche_qty in enumerate(tranches):
                if t_idx > 0:
                    time.sleep(2.0)  # TWAP-lite інтервал 2 с між траншами

                t_rem = tranche_qty
                # 3. Адаптивний 2-ітераційний BBO Chaser (2 x 4.5 с = 9 с)
                for iteration in (1, 2):
                    if t_rem < min_qty:
                        break

                    # Отримуємо свіжий BBO перед кожною ітерацією чейзера
                    cur_ob = self._exchange.fetch_order_book(ccxt_sym, limit=5)
                    cur_bids = cur_ob.get("bids") or []
                    cur_asks = cur_ob.get("asks") or []
                    cur_bid = float(cur_bids[0][0]) if cur_bids else best_bid
                    cur_ask = float(cur_asks[0][0]) if cur_asks else best_ask
                    limit_price = self.safe_price(clean_sym, cur_bid if side == "buy" else cur_ask)

                    params = {"postOnly": True}
                    if reduce_only:
                        params["reduceOnly"] = True

                    maker_order = None
                    try:
                        maker_order = self._exchange.create_order(
                            symbol=ccxt_sym,
                            type="limit",
                            side=side,
                            amount=t_rem,
                            price=limit_price,
                            params=params,
                        )
                    except Exception as e:
                        self._logger.debug(f"Maker order attempt {iteration} for {clean_sym} skipped: {e}")
                        maker_order = None

                    if maker_order and isinstance(maker_order, dict) and "id" in maker_order:
                        order_id = maker_order["id"]
                        last_order_id = str(order_id)
                        t0 = time.time()
                        iter_filled = False

                        # Очікуємо виконання до 4.5 секунд (перевірка кожні 1.0 с)
                        while (time.time() - t0) < 4.5:
                            time.sleep(1.0)
                            chk = self._exchange.fetch_order(order_id, ccxt_sym)
                            if chk and isinstance(chk, dict) and chk.get("status") == "closed":
                                f_qty = float(chk.get("filled") or t_rem)
                                f_price = float(chk.get("average") or chk.get("price") or limit_price)
                                f_fee = float((chk.get("fee") or {}).get("cost") or (f_qty * f_price * 0.0002))
                                total_maker_filled += f_qty
                                total_cost += (f_qty * f_price)
                                total_fee += f_fee
                                t_rem = max(0.0, t_rem - f_qty)
                                iter_filled = True
                                break

                        if not iter_filled:
                            # Скасовуємо ордер для перестановки BBO на 2-й ітерації або маркету
                            try:
                                self._exchange.cancel_order(order_id, ccxt_sym)
                            except Exception:
                                pass
                            try:
                                canceled = self._exchange.fetch_order(order_id, ccxt_sym)
                                if canceled and isinstance(canceled, dict):
                                    f_qty = float(canceled.get("filled") or 0.0)
                                    if f_qty > 0:
                                        f_price = float(canceled.get("average") or canceled.get("price") or limit_price)
                                        f_fee = float((canceled.get("fee") or {}).get("cost") or (f_qty * f_price * 0.0002))
                                        total_maker_filled += f_qty
                                        total_cost += (f_qty * f_price)
                                        total_fee += f_fee
                                        t_rem = max(0.0, t_rem - f_qty)
                            except Exception:
                                pass

                # 4. Taker Fallback на залишок траншу
                if t_rem >= min_qty:
                    m_qty = self.safe_amount(clean_sym, t_rem)
                    m_params = {"reduceOnly": True} if reduce_only else {}
                    try:
                        m_ord = self._exchange.create_market_order(ccxt_sym, side, m_qty, params=m_params)
                        if m_ord and isinstance(m_ord, dict):
                            f_qty = float(m_ord.get("filled") or m_qty)
                            f_price = float(m_ord.get("average") or m_ord.get("price") or est_price)
                            f_fee = float((m_ord.get("fee") or {}).get("cost") or (f_qty * f_price * 0.0005))
                            total_market_filled += f_qty
                            total_cost += (f_qty * f_price)
                            total_fee += f_fee
                            last_order_id = str(m_ord.get("id") or last_order_id)
                    except Exception as e:
                        err_s = str(e)
                        if "-2022" in err_s or "ReduceOnly" in err_s:
                            try:
                                m_ord = self._exchange.create_market_order(ccxt_sym, side, m_qty)
                                if m_ord and isinstance(m_ord, dict):
                                    f_qty = float(m_ord.get("filled") or m_qty)
                                    f_price = float(m_ord.get("average") or m_ord.get("price") or est_price)
                                    f_fee = float((m_ord.get("fee") or {}).get("cost") or (f_qty * f_price * 0.0005))
                                    total_market_filled += f_qty
                                    total_cost += (f_qty * f_price)
                                    total_fee += f_fee
                                    last_order_id = str(m_ord.get("id") or last_order_id)
                            except Exception as e2:
                                self._logger.info(f"ℹ️ [{clean_sym}] Позиція вже закрита на біржі: {e2}")
                        else:
                            self._logger.warning(f"⚠️ [{clean_sym}] Taker fallback помилка: {e}")

            tot_qty = total_maker_filled + total_market_filled
            if tot_qty <= 0.0:
                return None

            avg_p = total_cost / tot_qty if tot_qty > 0 else est_price
            self._db.record_trade(
                symbol=clean_sym,
                side=side,
                amount=tot_qty,
                price=avg_p,
                order_id=last_order_id,
                pnl=realized_pnl_est,
                fee=total_fee,
                note=note,
            )
            return OrderExecutionDTO(
                symbol=clean_sym,
                side=side.upper(),
                executed_qty=tot_qty,
                avg_price=avg_p,
                fee_usdt=total_fee,
                realized_pnl_est=realized_pnl_est,
                order_id=str(last_order_id),
                note=note,
            )
        except Exception as e:
            self._logger.error(f"❌ [{clean_sym}] Помилка виконання ордера: {e}")
            return None

    async def place_or_update_stop_loss(self, symbol: str, position_qty: float, stop_price: float) -> bool:
        return await asyncio.to_thread(self._place_stop_loss_sync, symbol, position_qty, stop_price)

    def _place_stop_loss_sync(self, symbol: str, position_qty: float, stop_price: float) -> bool:
        if self._exchange is None:
            return False
        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        qty = self.safe_amount(clean_sym, abs(position_qty))
        sl_p = self.safe_price(clean_sym, stop_price)
        if qty <= 0.0 or sl_p <= 0.0:
            return False

        close_side = "sell" if position_qty > 0 else "buy"
        try:
            open_ords = self._exchange.fetch_open_orders(ccxt_sym)
            for o in open_ords:
                if str(o.get("type") or "").lower() in ("stop_market", "stop"):
                    try:
                        self._exchange.cancel_order(o["id"], ccxt_sym)
                    except Exception:
                        pass

            try:
                self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="STOP_MARKET",
                    side=close_side,
                    amount=qty,
                    price=None,
                    params={
                        "stopPrice": sl_p,
                        "closePosition": True,
                        "workingType": "MARK_PRICE",
                    },
                )
            except Exception:
                self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="STOP_MARKET",
                    side=close_side,
                    amount=qty,
                    price=None,
                    params={
                        "stopPrice": sl_p,
                        "reduceOnly": True,
                        "workingType": "MARK_PRICE",
                    },
                )
            return True
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean_sym}] Не вдалося виставити SL @ {sl_p}: {e}")
            return False

    async def place_or_update_take_profit(self, symbol: str, position_qty: float, tp_price: float) -> bool:
        return await asyncio.to_thread(self._place_take_profit_sync, symbol, position_qty, tp_price)

    def _place_take_profit_sync(self, symbol: str, position_qty: float, tp_price: float) -> bool:
        if self._exchange is None:
            return False
        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        qty = self.safe_amount(clean_sym, abs(position_qty))
        tp_p = self.safe_price(clean_sym, tp_price)
        if qty <= 0.0 or tp_p <= 0.0:
            return False

        close_side = "sell" if position_qty > 0 else "buy"
        try:
            open_ords = self._exchange.fetch_open_orders(ccxt_sym)
            for o in open_ords:
                if str(o.get("type") or "").lower() in ("take_profit_market", "take_profit"):
                    try:
                        self._exchange.cancel_order(o["id"], ccxt_sym)
                    except Exception:
                        pass

            try:
                self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="TAKE_PROFIT_MARKET",
                    side=close_side,
                    amount=qty,
                    price=None,
                    params={
                        "stopPrice": tp_p,
                        "closePosition": True,
                        "workingType": "MARK_PRICE",
                    },
                )
            except Exception:
                self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="TAKE_PROFIT_MARKET",
                    side=close_side,
                    amount=qty,
                    price=None,
                    params={
                        "stopPrice": tp_p,
                        "reduceOnly": True,
                        "workingType": "MARK_PRICE",
                    },
                )
            return True
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean_sym}] Не вдалося виставити TP @ {tp_p}: {e}")
            return False

    async def place_passive_stink_bid(self, symbol: str, qty: float, price: float) -> Optional[str]:
        return await asyncio.to_thread(self._place_passive_stink_bid_sync, symbol, qty, price)

    def _place_passive_stink_bid_sync(self, symbol: str, qty: float, price: float) -> Optional[str]:
        if self._exchange is None:
            return None
        clean = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean)
        q = self.safe_amount(clean, qty)
        p = self.safe_price(clean, price)
        if q <= 0.0 or p <= 0.0:
            return None
        try:
            ord_res = self._exchange.create_order(
                symbol=ccxt_sym,
                type="limit",
                side="buy",
                amount=q,
                price=p,
                params={"postOnly": True},
            )
            return str(ord_res.get("id") or "")
        except Exception:
            return None

    async def cancel_all_stink_bids(self, symbols: Optional[Any] = None) -> int:
        return await asyncio.to_thread(self._cancel_all_stink_bids_sync, symbols)

    def _cancel_all_stink_bids_sync(self, symbols: Optional[Any] = None) -> int:
        if self._exchange is None:
            return 0
        syms_to_check = symbols or list(settings.SUPPORTED_SYMBOLS)
        canceled_cnt = 0
        for s in syms_to_check:
            clean = ccxt_to_symbol(s)
            ccxt_s = symbol_to_ccxt(clean)
            try:
                open_ords = self._exchange.fetch_open_orders(ccxt_s)
                for o in open_ords:
                    if str(o.get("type") or "").lower() == "limit":
                        try:
                            self._exchange.cancel_order(o["id"], ccxt_s)
                            canceled_cnt += 1
                        except Exception:
                            pass
            except Exception:
                pass
        return canceled_cnt

    async def cancel_symbol_orders(self, symbol: str) -> bool:
        return await asyncio.to_thread(self._cancel_symbol_orders_sync, symbol)

    def _cancel_symbol_orders_sync(self, symbol: str) -> bool:
        if self._exchange is None:
            return False
        clean = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean)
        try:
            self._exchange.cancel_all_orders(ccxt_sym)
            return True
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean}] Помилка скасування ордерів: {e}")
            return False

    async def emergency_liquidate_all(self, symbols: Tuple[str, ...]) -> str:
        return await asyncio.to_thread(self._emergency_liquidate_sync, symbols)

    def _emergency_liquidate_sync(self, symbols: Tuple[str, ...]) -> str:
        if self._exchange is None:
            return "❌ Біржовий шлюз не ініціалізовано."
        usdt_bal, _, pos_map, is_ok = self._fetch_account_snapshot_sync(symbols)
        if not is_ok:
            return "❌ Помилка зв'язку з біржею під час ліквідації."

        closed_lines = []
        for sym in symbols:
            clean = sym.upper()
            ccxt_sym = symbol_to_ccxt(clean)
            try:
                self._exchange.cancel_all_orders(ccxt_sym)
            except Exception:
                pass

            p_dto = pos_map.get(clean)
            if p_dto and abs(p_dto.contracts_qty) > 0:
                qty = self.safe_amount(clean, abs(p_dto.contracts_qty))
                min_q, _, _, _, _ = settings.get_symbol_spec(clean)
                if qty >= min_q:
                    side = "sell" if p_dto.contracts_qty > 0 else "buy"
                    try:
                        ord_res = self._exchange.create_market_order(
                            ccxt_sym, side, qty, params={"reduceOnly": True}
                        )
                        if ord_res and isinstance(ord_res, dict):
                            fill_p = float(ord_res.get("average") or ord_res.get("price") or p_dto.mark_price or 0.0)
                            fee_c = float((ord_res.get("fee") or {}).get("cost") or (qty * fill_p * 0.0005))
                            ord_id = ord_res.get("id")
                        else:
                            fill_p = float(p_dto.mark_price or 0.0)
                            fee_c = float(qty * fill_p * 0.0005)
                            ord_id = ""
                        self._db.record_trade(
                            symbol=clean,
                            side=side,
                            amount=qty,
                            price=fill_p,
                            order_id=ord_id,
                            pnl=p_dto.unrealized_pnl,
                            fee=fee_c,
                            note="PANIC_CLOSE_ALL",
                        )
                        closed_lines.append(f"• <b>{clean}</b>: закрито {qty} ({side.upper()}) | PnL: {p_dto.unrealized_pnl:+.2f}$")
                    except Exception as e:
                        closed_lines.append(f"• <b>{clean}</b>: помилка ({e})")

        if not closed_lines:
            return f"ℹ️ Відкритих позицій немає. 100% у кеші ({usdt_bal:,.2f} USDT)."
        return "🚨 <b>Ліквідовано в USDT:</b>\n" + "\n".join(closed_lines)