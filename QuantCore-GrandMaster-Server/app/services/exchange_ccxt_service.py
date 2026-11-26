import os
import json
import time
import hashlib
import asyncio
import logging
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple, Any, List
import ccxt
import pandas as pd

from app.core.config import settings, symbol_to_ccxt, ccxt_to_symbol
from app.domain.interfaces import IExchangeGateway
from app.domain.schemas import ExchangePositionDTO, OrderExecutionDTO
from app.services.database_service import DatabaseService
from app.services.smart_maker_executor import (
    CcxtSmartMakerAdapter,
    SmartMakerConfig,
    SmartMakerExecutor,
    compute_effective_fee_and_is_bps,
)


class ExchangeCcxtService(IExchangeGateway):
    """
    Мультивалютний клієнт Binance Futures (One-Way Mode) з:
    - In-Memory Ring-Buffer кешем свічок для 5+ монет.
    - Автоматичним обліком закритих біржею Stop-Loss ордерів у SQLite.
    """

    __slots__ = (
        "_logger", "_db", "_exchange", "_candles_cache",
        "_funding_hist_cache", "_oi_cache", "_depth_cache", "_last_order_diag",
        "_active_chase_symbols", "_smart_maker",
    )

    def __init__(self, logger: logging.Logger, db_service: DatabaseService) -> None:
        self._logger = logger
        self._db = db_service
        self._exchange: Optional[ccxt.binance] = None
        self._candles_cache: Dict[str, pd.DataFrame] = {}
        self._funding_hist_cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
        self._oi_cache: Dict[str, Tuple[float, float]] = {}
        self._depth_cache: Dict[str, Tuple[float, float]] = {}
        self._last_order_diag: Dict[str, Dict[str, Any]] = {}
        self._active_chase_symbols: set[str] = set()
        self._smart_maker = SmartMakerExecutor(
            adapter=CcxtSmartMakerAdapter(self),
            logger=logger,
            active_chase_symbols=self._active_chase_symbols,
        )

    @property
    def active_chase_symbols(self) -> set[str]:
        return self._active_chase_symbols

    def is_symbol_chasing(self, symbol: str) -> bool:
        return ccxt_to_symbol(symbol) in self._active_chase_symbols

    def get_last_order_diag(self, symbol: str) -> Dict[str, Any]:
        return dict(self._last_order_diag.get(ccxt_to_symbol(symbol), {}))

    @staticmethod
    def build_client_order_id(
        symbol: str,
        side: str,
        amount: float,
        reduce_only: bool,
        bucket_tag: str = "",
    ) -> str:
        """Детермінований Binance `newClientOrderId` (<= 36 символів `[a-zA-Z0-9_-]`) проти дублювання при таймауті."""
        clean = ccxt_to_symbol(symbol)[:12]
        sd = "B" if str(side).lower() == "buy" else "S"
        ro = "R" if reduce_only else "O"
        b_tag = str(bucket_tag or int(time.time() // 60))
        digest = hashlib.sha256(f"{clean}:{sd}:{ro}:{amount:.8f}:{b_tag}".encode("utf-8")).hexdigest()[:10]
        return f"qc6_{clean}_{sd}{ro}_{digest}"[:36]

    def _find_existing_order_by_client_id(self, ccxt_sym: str, client_order_id: str) -> Optional[Dict[str, Any]]:
        """Ідемпотентна перевірка: чи вже прийняла біржа ордер із цим `newClientOrderId` до таймауту мережі."""
        if self._exchange is None or not client_order_id:
            return None
        try:
            raw_s = ccxt_to_symbol(ccxt_sym)
            if hasattr(self._exchange, "fapiPrivateGetOrder") and not hasattr(self._exchange, "_mock_name"):
                res = self._exchange.fapiPrivateGetOrder({"symbol": raw_s, "origClientOrderId": client_order_id})
                if isinstance(res, dict) and (res.get("orderId") or res.get("clientOrderId")):
                    filled = float(res.get("executedQty") or 0.0)
                    avg_p = float(res.get("avgPrice") or res.get("price") or 0.0)
                    return {
                        "id": str(res.get("orderId") or client_order_id),
                        "status": str(res.get("status") or "").lower(),
                        "filled": filled,
                        "average": avg_p,
                        "price": avg_p,
                    }
        except Exception:
            pass
        return None

    def get_delisting_symbols(
        self,
        symbols: Tuple[str, ...],
        buffer_hours: Optional[float] = None,
        now_ms: Optional[int] = None,
    ) -> Dict[str, int]:
        """Виявляє ф'ючерси Binance USD-M із призначеною датою делістингу (`deliveryDate` в межах 72h або статус != TRADING)."""
        if self._exchange is None:
            return {}
        markets = getattr(self._exchange, "markets", None)
        if not isinstance(markets, dict) or not markets:
            return {}
        buf_h = float(settings.DELISTING_BUFFER_HOURS if buffer_hours is None else buffer_hours)
        cur_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        horizon_ms = cur_ms + int(buf_h * 3_600_000)
        # Активні безстрокові контракти Binance мають deliveryDate = 4133404800000 (2100 рік); будь-яка реальна дата <= horizon_ms = делістинг!
        perpetual_far_future_ms = 3_000_000_000_000
        flagged: Dict[str, int] = {}
        for sym in symbols:
            clean = ccxt_to_symbol(sym)
            c_sym = symbol_to_ccxt(clean)
            m = markets.get(c_sym)
            if not isinstance(m, dict):
                continue
            info = m.get("info") if isinstance(m.get("info"), dict) else {}
            status = str(info.get("status") or "TRADING").upper()
            deliv_raw = info.get("deliveryDate") or m.get("expiry") or 0
            try:
                deliv_ms = int(deliv_raw or 0)
            except Exception:
                deliv_ms = 0
            if status not in ("TRADING", "") or not bool(m.get("active", True)):
                flagged[clean] = deliv_ms or cur_ms
            elif 0 < deliv_ms < perpetual_far_future_ms and deliv_ms <= horizon_ms:
                flagged[clean] = deliv_ms
        return flagged

    def _is_listed_market(self, ccxt_sym: str) -> bool:
        """Перевіряє, чи існує символ на поточному стенді біржі (на Binance Demo є не всі 58 пар Mainnet)."""
        if self._exchange is None:
            return False
        markets = getattr(self._exchange, "markets", None)
        if not isinstance(markets, dict) or not markets:
            return True  # для unit-тестових MagicMock без завантаженого словника markets
        return ccxt_sym in markets

    def is_symbol_listed(self, symbol: str) -> bool:
        """Публічна перевірка лістингу пари на поточному стенді біржі (True для офлайн/тестових шлюзів)."""
        if self._exchange is None or hasattr(self._exchange, "_mock_name"):
            return True
        return self._is_listed_market(symbol_to_ccxt(ccxt_to_symbol(symbol)))

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
                "warnOnFetchOpenOrdersWithoutSymbol": False,
                "fetchOpenOrders": {"warnWithoutSymbol": False},
            },
        })
        if settings.USE_DEMO_TRADING:
            ex.enable_demo_trading(True)

        ex.load_markets()
        self._exchange = ex

        if settings.BINANCE_API_KEY:
            try:
                already_one_way = False
                if hasattr(ex, "fapiPrivateGetPositionSideDual") and not hasattr(ex, "_mock_name"):
                    dual_res = ex.fapiPrivateGetPositionSideDual() or {}
                    dual_val = dual_res.get("dualSidePosition")
                    if dual_val is False or str(dual_val).lower() == "false":
                        already_one_way = True
                if not already_one_way:
                    ex.set_position_mode(hedged=False)
            except Exception as e_pm:
                # Binance кидає -4059 / -4067 якщо One-Way вже активний або є захисні STOP_MARKET ордери
                err_s = str(e_pm)
                if "-4059" not in err_s and "-4067" not in err_s and "No need to change" not in err_s:
                    self._logger.warning(f"⚠️ Перевірка set_position_mode(One-Way): {type(e_pm).__name__}: {e_pm!r}")

            def _setup_margin_and_lev(sym_s: str) -> None:
                c_sym = symbol_to_ccxt(sym_s)
                if not self._is_listed_market(c_sym):
                    return
                # СУВОРО Cross Margin на всіх парах L/S кошика (Isolated Margin заборонено на малих рахунках!)
                try:
                    if hasattr(ex, "set_margin_mode"):
                        ex.set_margin_mode("cross", symbol=c_sym)
                except Exception as e_mm:
                    if "-4046" not in str(e_mm) and "No need to change margin type" not in str(e_mm):
                        self._logger.debug(f"[{sym_s}] set_margin_mode(cross): {e_mm}")
                try:
                    ex.set_leverage(settings.EXCHANGE_LEVERAGE, symbol=c_sym)
                except Exception:
                    pass

            with ThreadPoolExecutor(max_workers=min(6, max(1, len(settings.DEFAULT_SYMBOLS)))) as pool:
                list(pool.map(_setup_margin_and_lev, settings.DEFAULT_SYMBOLS))

            # Fail-Fast Startup Preflight (One-Way Mode, NTP skew < 1000ms, Live Withdrawals Disabled)
            pf = self._run_preflight_sync()
            if settings.STRICT_STARTUP_PREFLIGHT and not hasattr(ex, "_mock_name"):
                fatal_errs: List[str] = []
                if not pf.get("one_way_mode_ok", True):
                    fatal_errs.append("Hedge Mode active on Binance account (QuantCore requires One-Way Mode!)")
                if not pf.get("ntp_clock_ok", True):
                    fatal_errs.append(f"NTP clock skew {pf.get('ntp_clock_skew_ms')}ms >= {settings.MAX_NTP_CLOCK_SKEW_MS}ms!")
                if pf.get("isolated_margin_symbols"):
                    fatal_errs.append(f"Isolated margin still active on: {pf.get('isolated_margin_symbols')} (Cross Margin mandatory!)")
                if (not settings.USE_DEMO_TRADING) and not pf.get("withdrawals_disabled_ok", True):
                    fatal_errs.append("LIVE API key has enableWithdrawals=True (must be disabled before trading!)")
                if fatal_errs:
                    msg = " | ".join(fatal_errs)
                    self._logger.critical(f"🛑 [FAIL-FAST PREFLIGHT] Старт заблоковано: {msg}")
                    raise RuntimeError(f"FAIL_FAST_PREFLIGHT: {msg}")

        self._logger.info(
            f"✅ Шлюз Binance Futures готовий (Demo={settings.USE_DEMO_TRADING}, Cross Margin, Плече={settings.EXCHANGE_LEVERAGE}x)."
        )

    async def run_preflight_diagnostics(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self._run_preflight_sync)

    def _run_preflight_sync(self) -> Dict[str, Any]:
        from pathlib import Path
        from app.core.memory_guard import memory_guard

        _q_dir = Path(settings.BASE_DIR) / "quant_v2" / "models"
        if not _q_dir.exists():
            _q_dir = Path(settings.BASE_DIR).parent / "quant_v2" / "models"
        ml_v5_path = _q_dir / "ml_ranker_v5.joblib"
        ml_v4_path = _q_dir / "ml_ranker_v4.joblib"
        ml_v3_path = _q_dir / "ml_ranker_v3.joblib"
        ml_any_ok = ml_v5_path.exists() or ml_v4_path.exists() or ml_v3_path.exists()
        checks: Dict[str, Any] = {
            "api_keys_configured": bool(settings.BINANCE_API_KEY and settings.BINANCE_SECRET_KEY),
            "demo_trading_mode": bool(settings.USE_DEMO_TRADING),
            "virtual_equity_cap": float(settings.VIRTUAL_EQUITY_CAP),
            "cartridge_engine": settings.CARTRIDGE_ENGINE,
            "candle_timeframe": settings.CANDLE_TIMEFRAME,
            "symbols_count": len(settings.DEFAULT_SYMBOLS),
            "ml_ranker_v3_present": ml_any_ok,
            "ml_ranker_v4_present": ml_v5_path.exists() or ml_v4_path.exists(),
            "ml_ranker_v5_present": ml_v5_path.exists(),
            "ram_rss_mb": memory_guard.get_rss_mb(),
            "one_way_mode_ok": False,
            "cross_margin_ok": True,
            "isolated_margin_symbols": [],
            "ntp_clock_skew_ms": 0,
            "ntp_clock_ok": True,
            "withdrawals_disabled_ok": True,
            "delisting_soon_symbols": {},
            "multi_assets_margin": False,
            "bnb_fee_burn_balance": 0.0,
            "bfusd_collateral_balance": 0.0,
            "usdt_wallet_balance": 0.0,
            "exchange_reachable": False,
        }
        if self._exchange is None:
            return checks
        checks["exchange_reachable"] = True
        checks["delisting_soon_symbols"] = self.get_delisting_symbols(settings.DEFAULT_SYMBOLS)
        try:
            if hasattr(self._exchange, "fetch_time"):
                t_local_0 = time.time() * 1000.0
                srv_ms = self._exchange.fetch_time()
                t_local_1 = time.time() * 1000.0
                if isinstance(srv_ms, (int, float)) and srv_ms > 0:
                    mid_local = 0.5 * (t_local_0 + t_local_1)
                    skew_ms = int(round(abs(float(srv_ms) - mid_local)))
                    checks["ntp_clock_skew_ms"] = skew_ms
                    checks["ntp_clock_ok"] = bool(skew_ms < int(settings.MAX_NTP_CLOCK_SKEW_MS))
        except Exception:
            pass
        if not settings.BINANCE_API_KEY:
            return checks
        try:
            if hasattr(self._exchange, "fapiPrivateGetPositionSideDual"):
                dual = self._exchange.fapiPrivateGetPositionSideDual() or {}
                checks["one_way_mode_ok"] = not bool(dual.get("dualSidePosition", False))
            else:
                checks["one_way_mode_ok"] = True
        except Exception:
            checks["one_way_mode_ok"] = True
        try:
            if not settings.USE_DEMO_TRADING and hasattr(self._exchange, "sapiGetAccountApiRestrictions"):
                restr = self._exchange.sapiGetAccountApiRestrictions() or {}
                if isinstance(restr, dict) and "enableWithdrawals" in restr:
                    checks["withdrawals_disabled_ok"] = not bool(restr.get("enableWithdrawals"))
        except Exception:
            pass
        try:
            if hasattr(self._exchange, "fetch_positions"):
                active_set = {ccxt_to_symbol(s) for s in settings.DEFAULT_SYMBOLS}
                c_list = [symbol_to_ccxt(s) for s in settings.DEFAULT_SYMBOLS if self._is_listed_market(symbol_to_ccxt(s))]
                raw_pos = self._exchange.fetch_positions(c_list) if c_list else []
                iso_syms: List[str] = []
                if isinstance(raw_pos, list):
                    for rp in raw_pos:
                        if not isinstance(rp, dict):
                            continue
                        cs = ccxt_to_symbol(str(rp.get("symbol") or ""))
                        if cs not in active_set:
                            continue
                        m_mode = str(rp.get("marginMode") or (rp.get("info") or {}).get("marginType") or "").lower()
                        if m_mode == "isolated":
                            iso_syms.append(cs)
                checks["isolated_margin_symbols"] = sorted(set(iso_syms))
                checks["cross_margin_ok"] = len(iso_syms) == 0
        except Exception:
            pass
        try:
            if hasattr(self._exchange, "fapiPrivateGetMultiAssetsMargin"):
                mam = self._exchange.fapiPrivateGetMultiAssetsMargin() or {}
                checks["multi_assets_margin"] = bool(mam.get("multiAssetsMargin", False))
        except Exception:
            pass
        try:
            bal = self._exchange.fetch_balance() or {}
            tot = bal.get("total") or {}
            checks["usdt_wallet_balance"] = round(float(tot.get("USDT") or 0.0), 2)
            checks["bnb_fee_burn_balance"] = round(float(tot.get("BNB") or 0.0), 4)
            checks["bfusd_collateral_balance"] = round(float(tot.get("BFUSD") or 0.0), 2)
        except Exception:
            pass
        return checks

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

    async def sync_exchange_stop_closure(
        self,
        symbol: str,
        prev_pos_qty: float = 0.0,
        since_ms: int = 0,
    ) -> Optional[Tuple[float, float, float]]:
        """
        Викликається, коли відкрита позиція зникла на біржі (спрацював STOP_MARKET / TP).
        Скасовує залишкові ордери, зчитує фактичні закриваючі трейди та fapiPrivateGetIncome(REALIZED_PNL, COMMISSION),
        коректно фіксує CLOSE_SHORT (BUY) / CLOSE_LONG (SELL) і повертає (qty, avg_price, realized_pnl).
        """
        return await asyncio.to_thread(self._sync_exchange_stop_closure_sync, symbol, prev_pos_qty, since_ms)

    def _sync_exchange_stop_closure_sync(
        self,
        symbol: str,
        prev_pos_qty: float = 0.0,
        since_ms: int = 0,
    ) -> Optional[Tuple[float, float, float]]:
        if self._exchange is None:
            return None
        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        try:
            self._exchange.cancel_all_orders(ccxt_sym)
        except Exception:
            pass
        try:
            self._cancel_conditional_orders_sync(ccxt_sym)
        except Exception:
            pass

        expected_side = "BUY" if float(prev_pos_qty) < -1e-12 else ("SELL" if float(prev_pos_qty) > 1e-12 else "")
        action_str = "CLOSE_SHORT" if expected_side == "BUY" else ("CLOSE_LONG" if expected_side == "SELL" else "")
        eff_since = int(since_ms) if int(since_ms) > 0 else (int((time.time() - 7200.0) * 1000) if expected_side else 0)

        try:
            if eff_since > 0:
                try:
                    trades = self._exchange.fetch_my_trades(ccxt_sym, since=eff_since, limit=40)
                except TypeError:
                    trades = self._exchange.fetch_my_trades(ccxt_sym, limit=20)
            else:
                trades = self._exchange.fetch_my_trades(ccxt_sym, limit=6)

            valid_trades = [t for t in (trades or []) if isinstance(t, dict)]
            if expected_side:
                # Відсікаємо ордери ВХОДУ: закриття шорта ОБОВ'ЯЗКОВО має side=='BUY' та ненульовий realizedPnl (або свіжий час)
                side_matched = [
                    t for t in valid_trades
                    if str(t.get("side") or "").upper() == expected_side
                ]
                pnl_matched = [
                    t for t in side_matched
                    if abs(float((t.get("info") or {}).get("realizedPnl") or 0.0)) > 1e-12
                ]
                cand_trades = pnl_matched or side_matched
            else:
                cand_trades = valid_trades

            tot_qty = 0.0
            tot_fee = 0.0
            tot_pnl = 0.0
            avg_price = 0.0
            order_id_str = ""

            if cand_trades:
                if expected_side and len(cand_trades) > 1:
                    # Агрегуємо всі часткові філи останнього закриття (напр. 2 частинами по ROSEUSDT)
                    last_ts = int(cand_trades[-1].get("timestamp") or 0)
                    cluster = [
                        t for t in cand_trades
                        if last_ts <= 0 or abs(int(t.get("timestamp") or 0) - last_ts) <= 180_000
                    ] or [cand_trades[-1]]
                else:
                    last_oid = cand_trades[-1].get("order")
                    cluster = [t for t in cand_trades if t.get("order") == last_oid] or [cand_trades[-1]]

                tot_qty = sum(float(t.get("amount") or 0.0) for t in cluster)
                tot_cost = sum(float(t.get("amount") or 0.0) * float(t.get("price") or 0.0) for t in cluster)
                tot_fee = sum(abs(float((t.get("fee") or {}).get("cost") or 0.0)) for t in cluster)
                tot_pnl = sum(float((t.get("info") or {}).get("realizedPnl") or 0.0) for t in cluster)
                avg_price = (tot_cost / tot_qty) if tot_qty > 0 else float(cluster[-1].get("price") or 0.0)
                order_id_str = str(cluster[-1].get("order") or "")
                rec_side = expected_side or str(cluster[-1].get("side") or "SELL").upper()
            else:
                rec_side = expected_side or "SELL"

            # Резервна звірка з канонічним реєстром Binance fapiPrivateGetIncome(REALIZED_PNL, COMMISSION),
            # якщо userTrades ще не встиг віддати realizedPnl або повернув порожній список!
            if expected_side and abs(tot_pnl) <= 1e-12 and hasattr(self._exchange, "fapiPrivateGetIncome") and not hasattr(self._exchange.fapiPrivateGetIncome, "_mock_name"):
                try:
                    inc_st = eff_since if eff_since > 0 else int((time.time() - 7200.0) * 1000)
                    rp_rows = self._exchange.fapiPrivateGetIncome({
                        "symbol": clean_sym, "incomeType": "REALIZED_PNL", "startTime": inc_st, "limit": 50
                    }) or []
                    cm_rows = self._exchange.fapiPrivateGetIncome({
                        "symbol": clean_sym, "incomeType": "COMMISSION", "startTime": inc_st, "limit": 50
                    }) or []
                    if rp_rows:
                        tot_pnl = sum(float(r.get("income") or 0.0) for r in rp_rows if isinstance(r, dict))
                        if not order_id_str:
                            order_id_str = f"inc_{rp_rows[-1].get('tranId', '')}"
                    if cm_rows and tot_fee <= 1e-12:
                        tot_fee = sum(abs(float(r.get("income") or 0.0)) for r in cm_rows if isinstance(r, dict))
                    if tot_qty <= 0.0:
                        tot_qty = abs(float(prev_pos_qty))
                except Exception:
                    pass

            if tot_qty <= 0.0 and abs(tot_pnl) <= 1e-12:
                return None

            note_lbl = "MFE_HARVESTER_TP" if tot_pnl > 0.0 else "STOP_LOSS_EXCHANGE"
            rec_kwargs: Dict[str, Any] = {
                "symbol": clean_sym,
                "side": rec_side,
                "amount": tot_qty,
                "price": avg_price,
                "order_id": order_id_str,
                "pnl": tot_pnl,
                "fee": tot_fee,
                "note": note_lbl,
            }
            if action_str:
                rec_kwargs["action"] = action_str
            try:
                self._db.record_trade(**rec_kwargs)
            except TypeError:
                rec_kwargs.pop("action", None)
                self._db.record_trade(**rec_kwargs)
            return tot_qty, avg_price, tot_pnl
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean_sym}] Не вдалося зчитати деталі закритого стопа: {e}")
            return None

    async def fetch_account_income_ledger(self, since_ms: int) -> List[Dict[str, Any]]:
        """Зчитує канонічні записи REALIZED_PNL, COMMISSION та FUNDING_FEE з Binance USD-M за унікальним tranId."""
        return await asyncio.to_thread(self._fetch_account_income_ledger_sync, since_ms)

    def _fetch_account_income_ledger_sync(self, since_ms: int) -> List[Dict[str, Any]]:
        if self._exchange is None or not hasattr(self._exchange, "fapiPrivateGetIncome") or hasattr(self._exchange, "_mock_name"):
            return []
        out: List[Dict[str, Any]] = []
        for itype in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
            cur_since = int(since_ms) if since_ms > 0 else 0
            for _page in range(5):
                try:
                    params: Dict[str, Any] = {"incomeType": itype, "limit": 1000}
                    if cur_since > 0:
                        params["startTime"] = cur_since
                    rows = self._exchange.fapiPrivateGetIncome(params) or []
                    if not rows:
                        break
                    max_t = cur_since
                    for r in rows:
                        if not isinstance(r, dict):
                            continue
                        tid = str(r.get("tranId") or "").strip()
                        tms = int(r.get("time") or 0)
                        if not tid or tms <= 0:
                            continue
                        if tms > max_t:
                            max_t = tms
                        out.append({
                            "tran_id": f"{itype}_{tid}",
                            "ts_ms": tms,
                            "income_type": itype,
                            "symbol": str(r.get("symbol") or "").upper(),
                            "income_usdt": float(r.get("income") or 0.0),
                            "info": str(r.get("info") or ""),
                        })
                    if len(rows) < 1000 or max_t <= cur_since:
                        break
                    cur_since = max_t + 1
                except Exception:
                    break
        return out

    async def measure_ntp_skew_ms(self) -> Optional[int]:
        return await asyncio.to_thread(self._measure_ntp_skew_sync)

    def _measure_ntp_skew_sync(self) -> Optional[int]:
        if self._exchange is None or hasattr(self._exchange, "_mock_name"):
            return None
        try:
            t_loc_before = time.time() * 1000.0
            if hasattr(self._exchange, "fapiPublicGetTime"):
                srv_res = self._exchange.fapiPublicGetTime() or {}
                srv_ms = float(srv_res.get("serverTime") or 0.0)
            else:
                srv_ms = float(self._exchange.fetch_time() or 0.0)
            t_loc_after = time.time() * 1000.0
            if srv_ms <= 0:
                return None
            loc_mid = 0.5 * (t_loc_before + t_loc_after)
            return int(round(loc_mid - srv_ms))
        except Exception:
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
            info_bal = (bal.get("info") or {}) if isinstance(bal, dict) else {}
            raw_wb = info_bal.get("totalWalletBalance")
            if raw_wb is None and isinstance(info_bal.get("assets"), list):
                for a_item in info_bal["assets"]:
                    if isinstance(a_item, dict) and str(a_item.get("asset") or "").upper() == "USDT":
                        raw_wb = a_item.get("walletBalance")
                        break
            if raw_wb is not None:
                usdt_wallet = float(raw_wb)
            else:
                usdt_wallet = float(
                    (bal.get("total") or {}).get("USDT")
                    or (bal.get("free") or {}).get("USDT")
                    or 0.0
                )
            ccxt_syms = [symbol_to_ccxt(s) for s in symbols if self._is_listed_market(symbol_to_ccxt(s))]
            raw_positions = self._exchange.fetch_positions(ccxt_syms) if ccxt_syms else []

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
    def _klines_to_df(raw_klines: list, interval_minutes: Optional[int] = None) -> pd.DataFrame:
        rows = [
            {
                "open_ms": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "quote_volume": float(k[7]) if len(k) > 7 and k[7] is not None else float(k[4]) * float(k[5]),
                "count": float(k[8]) if len(k) > 8 and k[8] is not None else 0.0,
                "taker_base": float(k[9]) if len(k) > 9 and k[9] is not None else 0.0,
                "taker_buy_quote_volume": float(k[10]) if len(k) > 10 and k[10] is not None else float(k[9]) * float(k[4]),
            }
            for k in raw_klines
        ]
        df = pd.DataFrame(rows).drop_duplicates(subset=["open_ms"]).sort_values("open_ms").reset_index(drop=True)
        now_ms = time.time() * 1000.0
        candle_ms = int(interval_minutes or settings.CANDLE_INTERVAL_MINUTES) * 60 * 1000
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
            ccxt_syms = [symbol_to_ccxt(s) for s in symbols if self._is_listed_market(symbol_to_ccxt(s))]
            raw_fr = self._exchange.fetch_funding_rates(ccxt_syms) if ccxt_syms else {}
            rates: Dict[str, float] = {}
            for s in symbols:
                c_sym = symbol_to_ccxt(s)
                item = raw_fr.get(c_sym) or raw_fr.get(s) or {}
                rates[s.upper()] = float(item.get("fundingRate") or 0.0)
            return rates
        except Exception:
            return {}

    async def fetch_funding_history(
        self, symbols: Tuple[str, ...], hours: int = 720
    ) -> Dict[str, pd.DataFrame]:
        """Історія 8h-фандінгу для кожного символа (timestamp ms + funding_rate).

        Потрібна V2-рукаву для причинного funding_z_168: без історії ознака
        вироджується у константу, і фільтр перегріву не працює.
        """
        return await asyncio.to_thread(self._fetch_funding_history_sync, symbols, hours)

    def _fetch_funding_history_sync(
        self, symbols: Tuple[str, ...], hours: int
    ) -> Dict[str, pd.DataFrame]:
        if self._exchange is None:
            return {}
        now_s = time.time()
        ttl_sec = 7200.0  # 2h TTL: 8h фандінг змінюється раз на 4-8 годин -> нуль зайвих REST-запитів!
        since = int(now_s * 1000) - int(hours) * 3_600_000
        is_mock_ex = hasattr(self._exchange, "_mock_name")
        disk_f_path = Path(settings.MARKET_CACHE_DIR) / "funding_hist_cache.json"

        if not self._funding_hist_cache and not is_mock_ex and disk_f_path.exists():
            try:
                raw_disk = json.loads(disk_f_path.read_text(encoding="utf-8"))
                if isinstance(raw_disk, dict):
                    for s_k, entry in raw_disk.items():
                        if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], list) and entry[1]:
                            df_cached = pd.DataFrame(entry[1], columns=["timestamp", "funding_rate"])
                            self._funding_hist_cache[str(s_k).upper()] = (float(entry[0]), df_cached)
            except Exception:
                pass

        out: Dict[str, pd.DataFrame] = {}
        to_fetch: List[str] = []
        for sym in symbols:
            sym_u = sym.upper()
            cached = self._funding_hist_cache.get(sym_u)
            if cached is not None and (now_s - cached[0]) < ttl_sec:
                out[sym_u] = cached[1]
                continue
            ccxt_sym = symbol_to_ccxt(sym)
            if not self._is_listed_market(ccxt_sym):
                continue
            to_fetch.append(sym_u)

        def _pull_one(sym_u: str) -> Tuple[str, Optional[pd.DataFrame]]:
            ccxt_sym = symbol_to_ccxt(sym_u)
            try:
                raw = self._exchange.fetch_funding_rate_history(  # type: ignore[union-attr]
                    ccxt_sym, since=since, limit=1000
                )
                rows = [
                    {
                        "timestamp": int(ev["timestamp"]),
                        "funding_rate": float(ev.get("fundingRate") or 0.0),
                    }
                    for ev in (raw or [])
                    if ev.get("timestamp") is not None
                ]
                if rows:
                    df_h = (
                        pd.DataFrame(rows)
                        .drop_duplicates(subset=["timestamp"], keep="last")
                        .sort_values("timestamp")
                        .reset_index(drop=True)
                    )
                    return sym_u, df_h
            except Exception as e:
                self._logger.warning(
                    f"⚠️ Не вдалося завантажити funding history для {sym_u}: {type(e).__name__}: {e!r}"
                )
            return sym_u, None

        dirty_disk = False
        if to_fetch:
            n_workers = 1 if is_mock_ex else min(6, max(1, len(to_fetch)))
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                for sym_u, df_h in pool.map(_pull_one, to_fetch):
                    if df_h is not None:
                        self._funding_hist_cache[sym_u] = (now_s, df_h)
                        out[sym_u] = df_h
                        dirty_disk = True
                    elif sym_u in self._funding_hist_cache:
                        out[sym_u] = self._funding_hist_cache[sym_u][1]

        if dirty_disk and not is_mock_ex and self._funding_hist_cache:
            try:
                disk_f_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_f = disk_f_path.with_suffix(".json.tmp")
                serial_obj = {
                    s_k: [
                        round(float(ts_f), 3),
                        [[int(r["timestamp"]), float(r["funding_rate"])] for _, r in df_v.tail(260).iterrows()],
                    ]
                    for s_k, (ts_f, df_v) in self._funding_hist_cache.items()
                    if df_v is not None and not df_v.empty
                }
                tmp_f.write_text(json.dumps(serial_obj, separators=(",", ":")), encoding="utf-8")
                os.replace(tmp_f, disk_f_path)
            except Exception as disk_e:
                self._logger.debug(f"[FundingCache] Save skipped: {type(disk_e).__name__}: {disk_e!r}")
        return out

    async def fetch_funding_income(self, since_ms: int = 0) -> List[Dict[str, Any]]:
        """Реальні нарахування/списання FUNDING_FEE з рахунку Binance USD-M (Demo/Live)."""
        return await asyncio.to_thread(self._fetch_funding_income_sync, since_ms)

    def _fetch_funding_income_sync(self, since_ms: int = 0) -> List[Dict[str, Any]]:
        if self._exchange is None or not hasattr(self._exchange, "fapiPrivateGetIncome"):
            return []
        try:
            params: Dict[str, Any] = {"incomeType": "FUNDING_FEE", "limit": 200}
            if since_ms > 0:
                params["startTime"] = int(since_ms)
            raw = self._exchange.fapiPrivateGetIncome(params) or []
            out: List[Dict[str, Any]] = []
            for row in raw:
                if not isinstance(row, dict):
                    continue
                out.append({
                    "tran_id": str(row.get("tranId") or f"{row.get('symbol')}_{row.get('time')}"),
                    "funding_time_ms": int(row.get("time") or 0),
                    "symbol": str(row.get("symbol") or "").upper(),
                    "income_usdt": float(row.get("income") or 0.0),
                })
            return out
        except Exception:
            return []

    async def fetch_market_microstructure(self, symbols: Tuple[str, ...]) -> Dict[str, Dict[str, float]]:
        """Легкий пакетний знімок мікроструктури (BBO, спред, mark/index/basis, OI) для датасету V3."""
        return await asyncio.to_thread(self._fetch_market_micro_sync, symbols)

    def _fetch_market_micro_sync(self, symbols: Tuple[str, ...]) -> Dict[str, Dict[str, float]]:
        if self._exchange is None:
            return {}
        sym_set = {ccxt_to_symbol(s) for s in symbols}
        out: Dict[str, Dict[str, float]] = {}
        prem_map: Dict[str, Dict[str, Any]] = {}
        bbo_map: Dict[str, Dict[str, Any]] = {}
        try:
            if hasattr(self._exchange, "fapiPublicGetPremiumIndex"):
                for item in (self._exchange.fapiPublicGetPremiumIndex() or []):
                    s = str(item.get("symbol") or "").upper()
                    if s in sym_set:
                        prem_map[s] = item
        except Exception:
            pass
        try:
            if hasattr(self._exchange, "fapiPublicGetTickerBookTicker"):
                for item in (self._exchange.fapiPublicGetTickerBookTicker() or []):
                    s = str(item.get("symbol") or "").upper()
                    if s in sym_set:
                        bbo_map[s] = item
        except Exception:
            pass

        now_s = time.time()
        oi_ttl = 1500.0  # 25 хв кеш Open Interest -> миттєве виконання для 32 монет

        def _fetch_oi_one(sym_name: str, mp: float) -> Tuple[str, float]:
            if mp <= 0:
                return sym_name, 0.0
            cached_oi = self._oi_cache.get(sym_name)
            if cached_oi is not None and (now_s - cached_oi[0]) < oi_ttl:
                return sym_name, cached_oi[1]
            try:
                val = 0.0
                if settings.USE_DEMO_TRADING and not hasattr(self._exchange, "_mock_name"):
                    # На Binance Demo публічний fapiPublicGetOpenInterest повертає штучні сотні мільйонів паперових контрактів ($30T BTC).
                    # Читаємо реальний Open Interest із публічного Mainnet ендпоінта для чистоти v2_market_micro / V3 Data Lake!
                    req = urllib.request.Request(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym_name}")
                    with urllib.request.urlopen(req, timeout=4.0) as resp:
                        oi_raw = json.loads(resp.read().decode("utf-8")) or {}
                    val = float(oi_raw.get("openInterest") or 0.0) * mp
                elif hasattr(self._exchange, "fapiPublicGetOpenInterest"):
                    oi_raw = self._exchange.fapiPublicGetOpenInterest({"symbol": sym_name}) or {}
                    val = float(oi_raw.get("openInterest") or 0.0) * mp
                if not (0.0 <= val <= 200_000_000_000.0):
                    val = 0.0
                self._oi_cache[sym_name] = (now_s, val)
                return sym_name, val
            except Exception:
                pass
            return sym_name, 0.0

        mark_map = {sym: float(prem_map.get(sym, {}).get("markPrice") or 0.0) for sym in sym_set}
        oi_map: Dict[str, float] = {}
        if hasattr(self._exchange, "fapiPublicGetOpenInterest") and sym_set:
            with ThreadPoolExecutor(max_workers=min(4, max(1, len(sym_set)))) as pool:
                for s_k, v_oi in pool.map(lambda kv: _fetch_oi_one(kv[0], kv[1]), mark_map.items()):
                    oi_map[s_k] = v_oi

        for sym in sym_set:
            pr = prem_map.get(sym, {})
            bb = bbo_map.get(sym, {})
            mark_p = mark_map.get(sym, 0.0)
            idx_p = float(pr.get("indexPrice") or 0.0)
            fr = float(pr.get("lastFundingRate") or 0.0)
            bid = float(bb.get("bidPrice") or mark_p)
            ask = float(bb.get("askPrice") or mark_p)
            bid_q = float(bb.get("bidQty") or 0.0)
            ask_q = float(bb.get("askQty") or 0.0)
            mid = 0.5 * (bid + ask) if (bid > 0 and ask > 0) else mark_p
            spread_bps = ((ask - bid) / mid * 10_000.0) if mid > 0 else 0.0
            basis_bps = ((mark_p - idx_p) / idx_p * 10_000.0) if idx_p > 0 else 0.0
            cached_d = self._depth_cache.get(sym)
            bbo_depth_usd = (bid_q + ask_q) * max(mid, 0.0)
            top5_depth = cached_d[1] if (cached_d is not None and (now_s - cached_d[0]) < 120.0 and cached_d[1] > 0) else bbo_depth_usd
            out[sym] = {
                "best_bid": bid,
                "best_ask": ask,
                "spread_bps": round(spread_bps, 3),
                "top5_depth_usd": round(top5_depth, 2),
                "mark_price": mark_p,
                "index_price": idx_p,
                "basis_bps": round(basis_bps, 3),
                "open_interest_usd": round(oi_map.get(sym, 0.0), 2),
                "funding_rate": fr,
            }
        return out

    async def fetch_delta_candles(self, symbol: str, limit: int = settings.CANDLES_FETCH_LIMIT) -> Optional[pd.DataFrame]:
        return await asyncio.to_thread(self._fetch_delta_candles_sync, symbol, limit)

    def _fetch_delta_candles_sync(self, symbol: str, target_limit: int) -> Optional[pd.DataFrame]:
        if self._exchange is None:
            return None
        clean_sym = ccxt_to_symbol(symbol)
        if not self._is_listed_market(symbol_to_ccxt(clean_sym)):
            return None
        candle_ms = int(settings.CANDLE_INTERVAL_MINUTES) * 60 * 1000
        interval = settings.CANDLE_TIMEFRAME
        cached_df = self._candles_cache.get(clean_sym)
        disk_cache_path = Path(settings.MARKET_CACHE_DIR) / f"candles_{clean_sym}_{interval}.pkl"
        is_mock_ex = hasattr(self._exchange, "_mock_name")

        # Персистентний дисковий кеш свічок при рестарті сервісу (усуває 58x1500 холодний бурст і бан 429!)
        if cached_df is None and not is_mock_ex and disk_cache_path.exists():
            try:
                loaded_df = pd.read_pickle(disk_cache_path)
                if isinstance(loaded_df, pd.DataFrame) and len(loaded_df) >= 50:
                    cached_df = loaded_df
                    self._candles_cache[clean_sym] = loaded_df
            except Exception:
                pass

        def _persist_candles(df_save: pd.DataFrame) -> None:
            if is_mock_ex or df_save is None or df_save.empty:
                return
            try:
                tmp_p = disk_cache_path.with_suffix(".pkl.tmp")
                df_save.to_pickle(tmp_p)
                os.replace(tmp_p, disk_cache_path)
            except Exception:
                pass

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
                        "interval": interval,
                        "limit": min(120, missing_bars + 4),
                    })
                    if raw_tail:
                        tail_df = self._klines_to_df(raw_tail)
                        comb = pd.concat([cached_df, tail_df], ignore_index=True)
                        comb = comb.drop_duplicates(subset=["open_ms"], keep="last").sort_values("open_ms").reset_index(drop=True)
                        if len(comb) > target_limit:
                            comb = comb.iloc[-target_limit:].reset_index(drop=True)
                        self._candles_cache[clean_sym] = comb
                        _persist_candles(comb)
                        return comb

            all_klines = []
            end_ms = int(time.time() * 1000)
            while len(all_klines) < (target_limit + 5):
                batch_sz = min(1500, (target_limit + 5) - len(all_klines))
                raw_b = self._exchange.fapiPublicGetKlines({
                    "symbol": clean_sym,
                    "interval": interval,
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
            _persist_candles(df)
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
        maker_first: bool = False,
        taker_fallback: Optional[bool] = None,
        urgency: str = "normal",
        active_sl_price: float = 0.0,
        allow_smart_maker: bool = False,
    ) -> Optional[OrderExecutionDTO]:
        sm_cfg = SmartMakerConfig.from_settings(settings)
        if allow_smart_maker and sm_cfg.enabled:
            clean_sym = ccxt_to_symbol(symbol)
            ccxt_sym = symbol_to_ccxt(clean_sym)
            if self._exchange is None:
                return None
            if not self._is_listed_market(ccxt_sym):
                self._last_order_diag[clean_sym] = {
                    "exec_mode": "smart_maker",
                    "arrival_mid": float(mark_price),
                    "arrival_mid_px": float(mark_price),
                    "spread_bps": 0.0,
                    "latency_ms": 0.0,
                    "order_status": "UNLISTED_ON_DEMO",
                }
                return None
            res = await self._smart_maker.execute_smart_maker_order(
                symbol=clean_sym,
                delta_qty=delta_qty,
                mark_price=mark_price,
                realized_pnl_est=realized_pnl_est,
                note=note,
                reduce_only=reduce_only,
                active_sl_price=active_sl_price,
                force_market=False,
                cfg=sm_cfg,
            )
            self._last_order_diag[clean_sym] = res.telemetry.to_diag_dict()
            if res.dto is not None and self._db is not None:
                await asyncio.to_thread(
                    self._db.record_trade,
                    symbol=clean_sym,
                    side=res.dto.side.lower(),
                    amount=res.dto.executed_qty,
                    price=res.dto.avg_price,
                    order_id=str(res.dto.order_id or ""),
                    pnl=realized_pnl_est,
                    fee=res.dto.fee_usdt,
                    note=note,
                )
            return res.dto

        return await asyncio.to_thread(
            self._execute_smart_order_sync,
            symbol,
            delta_qty,
            mark_price,
            realized_pnl_est,
            note,
            reduce_only,
            maker_first,
            taker_fallback,
            urgency,
            active_sl_price,
        )

    @staticmethod
    def _is_reduce_only_2022(err: Any) -> bool:
        s = str(err)
        return ("-2022" in s) or ("ReduceOnly" in s)

    def _fetch_live_symbol_position_sync(self, ccxt_sym: str, clean_sym: str) -> Optional[float]:
        """Свіжий REST-запит поточної позиції на біржі для одного символа."""
        if self._exchange is None:
            return None
        try:
            raw_pos = self._exchange.fetch_positions([ccxt_sym])
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean_sym}] Не вдалося отримати живу позицію через REST: {e}")
            return None
        if not isinstance(raw_pos, (list, tuple)):
            return 0.0
        for p in raw_pos:
            if not isinstance(p, dict):
                continue
            p_sym = ccxt_to_symbol(str(p.get("symbol") or ""))
            if p_sym and p_sym != clean_sym:
                continue
            contracts = float(p.get("contracts") or 0.0)
            side_p = str(p.get("side") or "").lower()
            if contracts <= 0.0:
                continue
            if side_p == "short":
                return -contracts
            if side_p == "long":
                return contracts
            signed = float((p.get("info") or {}).get("positionAmt") or 0.0)
            if signed != 0.0:
                return signed
        return 0.0

    def _extract_order_exec_fields(
        self, ord_dict: Dict[str, Any], ccxt_sym: str, fallback_qty: float, fallback_price: float, fee_rate: float
    ) -> Tuple[float, float, float, str]:
        raw_filled = ord_dict.get("filled")
        if raw_filled is None:
            f_qty = fallback_qty if str(ord_dict.get("type") or "").lower() != "limit" else 0.0
        else:
            f_qty = float(raw_filled)
        if f_qty <= 0.0:
            return 0.0, 0.0, 0.0, str(ord_dict.get("id") or "")
        avg_exec = float(ord_dict.get("average") or ord_dict.get("price") or (ord_dict.get("info") or {}).get("avgPrice") or 0.0)
        if avg_exec <= 0.0 and ord_dict.get("id"):
            try:
                chk = self._exchange.fetch_order(ord_dict["id"], ccxt_sym)
                if isinstance(chk, dict):
                    avg_exec = float(chk.get("average") or chk.get("price") or (chk.get("info") or {}).get("avgPrice") or 0.0)
            except Exception:
                pass
        f_price = avg_exec if avg_exec > 0.0 else float(fallback_price)
        f_fee = float((ord_dict.get("fee") or {}).get("cost") or (f_qty * f_price * fee_rate))
        return f_qty, f_price, f_fee, str(ord_dict.get("id") or "")

    def _recover_2022_reduce_only_sync(
        self,
        clean_sym: str,
        ccxt_sym: str,
        side: str,
        requested_qty: float,
        min_qty: float,
        est_price: float,
        maker_mode: bool,
        allow_market_fallback: bool,
        limit_price: float,
        active_sl_price: float,
    ) -> Tuple[Optional[Dict[str, Any]], str, bool]:
        """Відновлення після Binance -2022 (ReduceOnly Order is rejected).

        Повертає (executed_order_dict_or_None, status_str, sl_rearmed_flag).
        """
        live_qty = self._fetch_live_symbol_position_sync(ccxt_sym, clean_sym)
        if live_qty is None:
            self._logger.error(f"🚨 [{clean_sym}] -2022 recovery: REST-запит позиції недоступний.")
            return None, "FAILED_2022_RETRY", False

        if abs(live_qty) < min_qty:
            self._logger.info(
                f"ℹ️ [{clean_sym}] -2022 підтверджено через REST (live_qty={live_qty:.6f} <= {min_qty}): "
                f"позиція вже закрита, чистимо залишкові ордери."
            )
            self._cancel_symbol_orders_with_sl_capture_sync(ccxt_sym, clean_sym)
            return None, "ALREADY_CLOSED_2022", False

        expected_close_side = "sell" if live_qty > 0 else "buy"
        if side != expected_close_side:
            self._logger.critical(
                f"🚨 [{clean_sym}] -2022 SIDE MISMATCH: side={side}, live_qty={live_qty:+.4f}. Скасовано без ретраю!"
            )
            return None, "FAILED_2022_SIDE_MISMATCH", False

        retry_qty = self.safe_amount(clean_sym, min(requested_qty, abs(live_qty)))
        if retry_qty < min_qty:
            return None, "ALREADY_CLOSED_2022", False

        is_full_exit = retry_qty >= (abs(live_qty) - min_qty * 0.5)
        self._logger.warning(
            f"🔄 [{clean_sym}] -2022 але live_qty={live_qty:+.4f}: скасовуємо блокуючі ордери та повторюємо "
            f"{'CLOSE' if is_full_exit else 'TRIM'} qty={retry_qty}."
        )

        captured_sl_px = 0.0
        retry_filled = 0.0
        retry_ord: Optional[Dict[str, Any]] = None
        sl_rearmed = False
        try:
            _, captured_sl_px = self._cancel_symbol_orders_with_sl_capture_sync(ccxt_sym, clean_sym)

            if maker_mode and limit_price > 0.0:
                mk_cid = self.build_client_order_id(
                    clean_sym, side, retry_qty, True, bucket_tag=f"r22mk_{int(time.time() // 60)}"
                )
                try:
                    mk_ord = self._exchange.create_order(
                        symbol=ccxt_sym,
                        type="limit",
                        side=side,
                        amount=retry_qty,
                        price=limit_price,
                        params={"postOnly": True, "reduceOnly": True, "newClientOrderId": mk_cid},
                    )
                    if isinstance(mk_ord, dict) and mk_ord.get("id"):
                        if str(mk_ord.get("status") or "").lower() == "closed" or float(mk_ord.get("filled") or 0.0) > 0.0:
                            retry_ord = mk_ord
                        else:
                            try:
                                self._exchange.cancel_order(mk_ord["id"], ccxt_sym)
                            except Exception:
                                pass
                            try:
                                chk = self._exchange.fetch_order(mk_ord["id"], ccxt_sym)
                                if isinstance(chk, dict) and float(chk.get("filled") or 0.0) > 0.0:
                                    retry_ord = chk
                            except Exception:
                                pass
                except Exception as mk_e:
                    self._logger.warning(f"⚠️ [{clean_sym}] Повторний postOnly після -2022 не вдався: {mk_e}")

            rem_retry = retry_qty
            if retry_ord is not None:
                f_q = float(retry_ord.get("filled") or 0.0)
                retry_filled += f_q
                rem_retry = self.safe_amount(clean_sym, max(0.0, retry_qty - f_q))

            if rem_retry >= min_qty and (is_full_exit or allow_market_fallback or not maker_mode):
                tk_cid = self.build_client_order_id(
                    clean_sym, side, rem_retry, True, bucket_tag=f"r22tk_{int(time.time() // 60)}"
                )
                try:
                    m_ord = self._exchange.create_market_order(
                        ccxt_sym,
                        side,
                        rem_retry,
                        params={"reduceOnly": True, "newClientOrderId": tk_cid, "newOrderRespType": "RESULT"},
                    )
                    if isinstance(m_ord, dict):
                        f_m = m_ord.get("filled")
                        f_mq = rem_retry if f_m is None else float(f_m)
                        if f_mq > 0.0:
                            retry_filled += f_mq
                            retry_ord = m_ord
                except Exception as m_e:
                    self._logger.error(f"🚨 [{clean_sym}] Повторний MARKET reduceOnly після -2022 не вдався: {m_e}")

            if retry_filled > 0.0 and retry_ord is not None:
                res_ord, res_status = retry_ord, "FILLED_2022_RETRY"
            else:
                res_ord, res_status = None, "FAILED_2022_RETRY"
        finally:
            eff_sl = float(active_sl_price or 0.0) if float(active_sl_price or 0.0) > 0.0 else captured_sl_px
            if eff_sl > 0.0:
                signed_delta_done = retry_filled if side == "buy" else -retry_filled
                rem_est = live_qty + signed_delta_done
                live_after = self._fetch_live_symbol_position_sync(ccxt_sym, clean_sym)
                if live_after is not None and (retry_filled <= 0.0 or abs(live_after - live_qty) > 1e-12):
                    rem_signed = live_after
                else:
                    rem_signed = rem_est
                if abs(rem_signed) >= min_qty:
                    ok_rearm, _ = self._place_stop_loss_ex_sync(clean_sym, rem_signed, eff_sl)
                    if ok_rearm:
                        sl_rearmed = True
                        self._logger.info(
                            f"🛡️ [{clean_sym}] Перевиставлено STOP_MARKET @ ${eff_sl:,.4f} на залишок {rem_signed:+.4f} після -2022."
                        )
                        self._last_order_diag.setdefault(clean_sym, {})["sl_rearmed_after_2022"] = True
        return res_ord, res_status, sl_rearmed

    def _execute_smart_order_sync(
        self,
        symbol: str,
        delta_qty: float,
        mark_price: float,
        realized_pnl_est: float,
        note: str,
        reduce_only: bool,
        maker_first: bool = False,
        taker_fallback: Optional[bool] = None,
        urgency: str = "normal",
        active_sl_price: float = 0.0,
    ) -> Optional[OrderExecutionDTO]:
        if self._exchange is None:
            return None
        t_start_ord = time.perf_counter()

        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        if not self._is_listed_market(ccxt_sym):
            self._last_order_diag[clean_sym] = {
                "arrival_mid_px": float(mark_price),
                "spread_bps": 0.0,
                "latency_ms": 0.0,
                "order_status": "UNLISTED_ON_DEMO",
            }
            return None
        side = "buy" if delta_qty > 0 else "sell"
        min_qty, _, min_notional, _, _ = settings.get_symbol_spec(clean_sym)

        amount = self.safe_amount(clean_sym, abs(delta_qty))
        if amount < min_qty:
            self._last_order_diag[clean_sym] = {
                "arrival_mid_px": float(mark_price),
                "spread_bps": 0.0,
                "latency_ms": round((time.perf_counter() - t_start_ord) * 1000.0, 1),
                "order_status": "REJECTED_MIN_QTY",
            }
            return None

        try:
            # 1. Глибина стакана та перевірка спреду (limit=20)
            ob = self._exchange.fetch_order_book(ccxt_sym, limit=20)
            bids = ob.get("bids") or []
            asks = ob.get("asks") or []
            best_bid = float(bids[0][0]) if bids else mark_price
            best_ask = float(asks[0][0]) if asks else mark_price
            arrival_mid = 0.5 * (best_bid + best_ask) if (best_bid > 0 and best_ask > 0) else mark_price
            spread_pct = (best_ask - best_bid) / max(1e-8, best_bid)
            spread_bps_val = round(float(spread_pct * 10_000.0), 3)

            # Зберігаємо реальну глибину топ-5 рівнів (bid+ask у USD) для телеметрії мікроструктури V2
            top5_usd = sum(float(b[0]) * float(b[1]) for b in bids[:5] if len(b) >= 2) + sum(float(a[0]) * float(a[1]) for a in asks[:5] if len(a) >= 2)
            if top5_usd > 0:
                self._depth_cache[clean_sym] = (time.time(), float(top5_usd))

            if not reduce_only and spread_pct > settings.MAX_ALLOWED_SPREAD_PCT:
                self._logger.warning(f"⚠️ [{clean_sym}] Спред {spread_pct*100:.3f}% перевищує ліміт. Пропуск входу.")
                self._last_order_diag[clean_sym] = {
                    "arrival_mid_px": float(arrival_mid),
                    "spread_bps": spread_bps_val,
                    "latency_ms": round((time.perf_counter() - t_start_ord) * 1000.0, 1),
                    "order_status": "REJECTED_SPREAD",
                }
                return None

            est_price = best_ask if side == "buy" else best_bid
            if (amount * est_price) < min_notional and not reduce_only:
                self._last_order_diag[clean_sym] = {
                    "arrival_mid_px": float(arrival_mid),
                    "spread_bps": spread_bps_val,
                    "latency_ms": round((time.perf_counter() - t_start_ord) * 1000.0, 1),
                    "order_status": "REJECTED_MIN_NOTIONAL",
                }
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
            status_2022_override: Optional[str] = None
            sl_rearmed_2022 = False
            allow_fb = bool(taker_fallback) if taker_fallback is not None else not (maker_first and not reduce_only)

            for t_idx, tranche_qty in enumerate(tranches):
                if t_idx > 0:
                    time.sleep(2.0)  # TWAP-lite інтервал 2 с між траншами

                t_rem = tranche_qty
                # 3. Легасі maker_first (V2/V58); V6.2-B Smart Maker делегується окремо в SmartMakerExecutor
                eff_maker_mode = bool(maker_first)
                n_max_chase = 2 if maker_first else 0
                chaser_iters = tuple(range(1, n_max_chase + 1))
                requotes_done = 0
                last_limit_placed = 0.0
                for iteration in chaser_iters:
                    if t_rem < min_qty:
                        break

                    # Отримуємо свіжий BBO перед кожною ітерацією чейзера
                    cur_ob = self._exchange.fetch_order_book(ccxt_sym, limit=5)
                    cur_bids = cur_ob.get("bids") or []
                    cur_asks = cur_ob.get("asks") or []
                    cur_bid = float(cur_bids[0][0]) if cur_bids else best_bid
                    cur_ask = float(cur_asks[0][0]) if cur_asks else best_ask
                    q_b3 = sum(float(b[1]) for b in cur_bids[:3] if len(b) >= 2)
                    q_a3 = sum(float(a[1]) for a in cur_asks[:3] if len(a) >= 2)
                    obi = (q_b3 - q_a3) / max(q_b3 + q_a3, 1e-9)
                    tk_sz = settings.get_tick_size(clean_sym)
                    raw_lim = cur_bid if side == "buy" else cur_ask
                    if tk_sz > 0:
                        sp_abs = cur_ask - cur_bid
                        favorable_flow = (side == "buy" and obi < -0.45) or (side == "sell" and obi > 0.45)
                        running_away = (side == "buy" and obi > 0.35) or (side == "sell" and obi < -0.35)
                        min_sp_mult = 1.95 if running_away else 2.95
                        if (not favorable_flow) and sp_abs >= (min_sp_mult * tk_sz):
                            raw_lim = (cur_bid + tk_sz) if side == "buy" else (cur_ask - tk_sz)
                    limit_price = self.safe_price(clean_sym, raw_lim)
                    last_limit_placed = limit_price
                    if iteration > 1:
                        requotes_done += 1

                    mk_cid = self.build_client_order_id(
                        clean_sym, side, t_rem, reduce_only, bucket_tag=f"mk{t_idx}_{iteration}_{int(time.time()//60)}"
                    )
                    params: Dict[str, Any] = {"postOnly": True, "newClientOrderId": mk_cid}
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
                        if reduce_only and self._is_reduce_only_2022(e):
                            rec_ord, status_2022_override, sl_rearmed_2022 = self._recover_2022_reduce_only_sync(
                                clean_sym=clean_sym,
                                ccxt_sym=ccxt_sym,
                                side=side,
                                requested_qty=t_rem,
                                min_qty=min_qty,
                                est_price=est_price,
                                maker_mode=True,
                                allow_market_fallback=allow_fb,
                                limit_price=limit_price,
                                active_sl_price=active_sl_price,
                            )
                            if rec_ord is not None:
                                r_qty, r_px, r_fee, r_id = self._extract_order_exec_fields(
                                    rec_ord, ccxt_sym, t_rem, est_price, 0.0005
                                )
                                if r_qty > 0.0:
                                    if str(rec_ord.get("type") or "").lower() == "limit":
                                        total_maker_filled += r_qty
                                    else:
                                        total_market_filled += r_qty
                                    total_cost += r_qty * r_px
                                    total_fee += r_fee
                                    last_order_id = r_id or last_order_id
                                    t_rem = max(0.0, t_rem - r_qty)
                            break
                        self._logger.debug(f"Maker order attempt {iteration} for {clean_sym} skipped: {e}")
                        maker_order = None

                    if maker_order and isinstance(maker_order, dict) and "id" in maker_order:
                        order_id = maker_order["id"]
                        last_order_id = str(order_id)
                        t0 = time.time()
                        iter_filled = False

                        if eff_maker_mode and taker_fallback is True:
                            wait_lim = float(settings.V3_URGENT_MAKER_WAIT_SEC if urgency == "high" else settings.V2_MAKER_WAIT_SEC)
                            poll_sec = 0.45
                        else:
                            wait_lim = 5.5 if eff_maker_mode else 4.5
                            poll_sec = 1.0
                        while (time.time() - t0) < wait_lim:
                            time.sleep(poll_sec)
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

                if status_2022_override is not None:
                    break

                # 4. Захищене виконання залишку: Protected Limit IOC (BBO ± max_slip) на вхід або ReduceOnly на вихід!
                if t_rem >= min_qty and allow_fb:
                    m_qty = self.safe_amount(clean_sym, t_rem)
                    tk_cid = self.build_client_order_id(
                        clean_sym, side, m_qty, reduce_only, bucket_tag=f"tk{t_idx}_{int(time.time()//60)}"
                    )
                    existing_ord = self._find_existing_order_by_client_id(ccxt_sym, tk_cid)
                    m_ord = existing_ord
                    if m_ord is None:
                        try:
                            if not reduce_only and not maker_first:
                                # V6.1 Protected Limit IOC: миттєве виконання без ризику "прострілу" порожнього стакана!
                                max_slip = float(settings.PROTECTED_IOC_MAX_SLIP_PCT)
                                raw_ioc = best_ask * (1.0 + max_slip) if side == "buy" else best_bid * (1.0 - max_slip)
                                ioc_px = self.safe_price(clean_sym, raw_ioc)
                                ioc_params: Dict[str, Any] = {
                                    "timeInForce": "IOC",
                                    "newClientOrderId": tk_cid,
                                    "newOrderRespType": "RESULT",
                                }
                                m_ord = self._exchange.create_order(
                                    symbol=ccxt_sym,
                                    type="limit",
                                    side=side,
                                    amount=m_qty,
                                    price=ioc_px,
                                    params=ioc_params,
                                )
                            else:
                                m_params: Dict[str, Any] = {
                                    "newClientOrderId": tk_cid,
                                    "newOrderRespType": "RESULT",
                                }
                                if reduce_only:
                                    m_params["reduceOnly"] = True
                                m_ord = self._exchange.create_market_order(ccxt_sym, side, m_qty, params=m_params)
                        except Exception as e:
                            # КРИТИЧНЕ ВИПРАВЛЕННЯ БЕЗПЕКИ (-2022):
                            # НІКОЛИ не повторюємо ордер без `reduceOnly=True`!
                            if reduce_only and self._is_reduce_only_2022(e):
                                m_ord, status_2022_override, sl_rearmed_2022 = self._recover_2022_reduce_only_sync(
                                    clean_sym=clean_sym,
                                    ccxt_sym=ccxt_sym,
                                    side=side,
                                    requested_qty=m_qty,
                                    min_qty=min_qty,
                                    est_price=est_price,
                                    maker_mode=False,
                                    allow_market_fallback=True,
                                    limit_price=0.0,
                                    active_sl_price=active_sl_price,
                                )
                                if m_ord is None:
                                    break
                            elif self._is_reduce_only_2022(e):
                                status_2022_override = "ALREADY_CLOSED_2022"
                                break
                            else:
                                rec_ord = self._find_existing_order_by_client_id(ccxt_sym, tk_cid)
                                if rec_ord is not None:
                                    m_ord = rec_ord
                                else:
                                    self._logger.warning(f"⚠️ [{clean_sym}] Помилка виконання IOC/Taker ордера: {e}")

                    if m_ord and isinstance(m_ord, dict):
                        f_qty, f_price, f_fee, f_id = self._extract_order_exec_fields(
                            m_ord, ccxt_sym, m_qty, est_price, 0.0005
                        )
                        if f_qty > 0.0:
                            total_market_filled += f_qty
                            total_cost += (f_qty * f_price)
                            total_fee += f_fee
                            last_order_id = f_id or last_order_id

            tot_qty = total_maker_filled + total_market_filled
            lat_ms = round((time.perf_counter() - t_start_ord) * 1000.0, 1)
            if tot_qty <= 0.0:
                self._last_order_diag[clean_sym] = {
                    "arrival_mid_px": float(arrival_mid),
                    "spread_bps": spread_bps_val,
                    "latency_ms": lat_ms,
                    "sl_rearmed_after_2022": sl_rearmed_2022,
                    "order_status": (
                        status_2022_override
                        if status_2022_override is not None
                        else ("UNFILLED" if (maker_first and not allow_fb) else "REJECTED")
                    ),
                }
                return None

            avg_p = total_cost / tot_qty if tot_qty > 0 else est_price
            side_sign = 1.0 if side == "buy" else -1.0
            slip_bps = ((avg_p - arrival_mid) / max(arrival_mid, 1e-8) * side_sign * 10_000.0) if arrival_mid > 0 else 0.0
            is_maker_flag = bool(total_maker_filled > 0.0 and total_market_filled <= 1e-12)
            fb_used_flag = bool(total_market_filled > 1e-12)
            status_str = "FILLED" if tot_qty >= (amount - min_qty * 0.5) else "PARTIAL"
            mk_ratio_val = round(float(total_maker_filled / tot_qty), 4) if tot_qty > 0 else 0.0
            exec_mode_val = (
                "smart_maker"
                if is_maker_flag
                else ("market_fallback" if (eff_maker_mode and fb_used_flag) else "market_direct")
            )
            _, eff_fee_bps_val, is_bps_val = compute_effective_fee_and_is_bps(
                side=side.upper(),
                arrival_mid=float(arrival_mid),
                avg_fill_price=float(avg_p),
                maker_filled_qty=float(total_maker_filled),
                taker_filled_qty=float(total_market_filled),
                explicit_fee_usdt=float(total_fee),
                has_complete_explicit_fee=bool(total_fee > 0.0),
            )

            self._last_order_diag[clean_sym] = {
                "exec_mode": exec_mode_val,
                "arrival_mid": float(arrival_mid),
                "arrival_mid_px": float(arrival_mid),
                "avg_fill_price": float(avg_p),
                "maker_filled_qty": round(float(total_maker_filled), 8),
                "taker_filled_qty": round(float(total_market_filled), 8),
                "maker_fill_ratio": mk_ratio_val,
                "chase_attempts": int(requotes_done + (1 if last_limit_placed > 0 else 0)),
                "cancel_count": int(requotes_done + (1 if (eff_maker_mode and fb_used_flag) else 0)),
                "post_only_rejects_5022": 0,
                "drift_abort": False,
                "effective_fee_bps": eff_fee_bps_val,
                "implementation_shortfall_bps": is_bps_val,
                "spread_bps": spread_bps_val,
                "bbo_spread_bps": spread_bps_val,
                "best_bid": float(best_bid),
                "best_ask": float(best_ask),
                "top5_depth_usd": round(float(top5_usd), 2),
                "limit_placed_price": float(last_limit_placed),
                "requotes_count": int(requotes_done),
                "sl_rearmed_after_2022": sl_rearmed_2022,
                "fallback_reason": "maker_unfilled_ioc_fallback" if (eff_maker_mode and fb_used_flag) else ("direct_ioc" if fb_used_flag else "maker_filled"),
                "latency_ms": lat_ms,
                "order_status": status_2022_override or status_str,
            }
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
                maker_qty=float(total_maker_filled),
                taker_qty=float(total_market_filled),
                arrival_price=float(arrival_mid),
                arrival_mid_px=float(arrival_mid),
                spread_bps=spread_bps_val,
                slippage_bps=round(float(slip_bps), 3),
                latency_ms=lat_ms,
                is_maker=is_maker_flag,
                maker_fallback_used=fb_used_flag,
                order_status=status_str,
            )
        except Exception as e:
            self._logger.error(f"❌ [{clean_sym}] Помилка виконання ордера: {e}")
            self._last_order_diag[clean_sym] = {
                "arrival_mid_px": float(mark_price),
                "spread_bps": 0.0,
                "latency_ms": round((time.perf_counter() - t_start_ord) * 1000.0, 1),
                "order_status": "ERROR",
            }
            return None

    @staticmethod
    def _extract_order_type(o: Any) -> str:
        """Надійно визначає реальний тип ордера (включно з Binance Algo/Trigger CONDITIONAL, де o['type']=='market', а info['orderType']=='STOP_MARKET'!)."""
        if not isinstance(o, dict):
            return ""
        inf = o.get("info") if isinstance(o.get("info"), dict) else {}
        raw_t = str(
            inf.get("orderType")
            or inf.get("origType")
            or inf.get("type")
            or o.get("type")
            or ""
        ).strip().lower()
        if raw_t == "market":
            has_trig = bool(
                str(inf.get("algoType") or "").upper() == "CONDITIONAL"
                or o.get("stopPrice")
                or o.get("triggerPrice")
                or inf.get("stopPrice")
                or inf.get("triggerPrice")
            )
            if has_trig:
                return "stop_market"
        return raw_t

    def _cancel_conditional_orders_sync(
        self, ccxt_sym: str, types_filter: Optional[Tuple[str, ...]] = None
    ) -> int:
        """Скасовує І звичайні, І умовні Algo/Trigger ордери (`params={'trigger': True}`) на Binance USD-M!"""
        if self._exchange is None:
            return 0
        canceled = 0
        for is_trig in (False, True):
            try:
                ords = (
                    self._exchange.fetch_open_orders(ccxt_sym, params={"trigger": True})
                    if is_trig
                    else self._exchange.fetch_open_orders(ccxt_sym)
                )
            except TypeError:
                # Якщо mock у тестах не приймає params=...
                if is_trig:
                    continue
                ords = self._exchange.fetch_open_orders(ccxt_sym)
            except Exception:
                continue
            for o in (ords or []):
                if not isinstance(o, dict) or "id" not in o:
                    continue
                o_type = self._extract_order_type(o)
                if types_filter is not None and o_type and o_type not in types_filter:
                    continue
                try:
                    if is_trig:
                        self._exchange.cancel_order(o["id"], ccxt_sym, params={"trigger": True})
                    else:
                        self._exchange.cancel_order(o["id"], ccxt_sym)
                    canceled += 1
                except Exception:
                    pass
        return canceled

    async def place_or_update_stop_loss(self, symbol: str, position_qty: float, stop_price: float) -> bool:
        ok, _reason = await self.place_or_update_stop_loss_ex(symbol, position_qty, stop_price)
        return ok

    async def place_or_update_stop_loss_ex(
        self, symbol: str, position_qty: float, stop_price: float
    ) -> Tuple[bool, str]:
        return await asyncio.to_thread(self._place_stop_loss_ex_sync, symbol, position_qty, stop_price)

    def _place_stop_loss_sync(self, symbol: str, position_qty: float, stop_price: float) -> bool:
        return self._place_stop_loss_ex_sync(symbol, position_qty, stop_price)[0]

    def _place_stop_loss_ex_sync(self, symbol: str, position_qty: float, stop_price: float) -> Tuple[bool, str]:
        if self._exchange is None:
            return False, "NO_EXCHANGE"
        clean_sym = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        qty = self.safe_amount(clean_sym, abs(position_qty))
        sl_p = self.safe_price(clean_sym, stop_price)
        if qty <= 0.0 or sl_p <= 0.0:
            return False, "INVALID_QTY_OR_PRICE"

        close_side = "sell" if position_qty > 0 else "buy"
        nonce_ms = int(time.time() * 1000) % 10_000_000
        sl_cid = self.build_client_order_id(clean_sym, close_side, qty, True, bucket_tag=f"sl_{sl_p}_{nonce_ms}")
        sl_cid_fb = self.build_client_order_id(clean_sym, close_side, qty, True, bucket_tag=f"slf_{sl_p}_{nonce_ms}")
        try:
            self._cancel_conditional_orders_sync(ccxt_sym, types_filter=("stop_market", "stop"))

            try:
                # 100% позиційний STOP_MARKET з closePosition=True (без amount/quantity та reduceOnly, щоб уникнути -1106 і не займати квоту reduceOnly)
                self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="STOP_MARKET",
                    side=close_side,
                    amount=None,
                    price=None,
                    params={
                        "stopPrice": sl_p,
                        "closePosition": True,
                        "workingType": "MARK_PRICE",
                        "newClientOrderId": sl_cid,
                    },
                )
                return True, "OK"
            except Exception as err1:
                e1_str = str(err1)
                if "-2021" in e1_str or "immediately trigger" in e1_str.lower():
                    self._logger.error(
                        f"🚨 [{clean_sym}] STOP_MARKET @ {sl_p} відхилено з -2021 (ціна вже пробила стоп)! "
                        f"Негайний аварійний вихід reduceOnly!"
                    )
                    return False, "IMMEDIATE_TRIGGER_2021"
                time.sleep(0.25)
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
                        "newClientOrderId": sl_cid_fb,
                    },
                )
                return True, "OK_FALLBACK"
        except Exception as e:
            e_str = str(e)
            if "-2021" in e_str or "immediately trigger" in e_str.lower():
                self._logger.error(
                    f"🚨 [{clean_sym}] STOP_MARKET @ {sl_p} відхилено з -2021 (ціна вже пробила стоп)! "
                    f"Негайний аварійний вихід reduceOnly!"
                )
                return False, "IMMEDIATE_TRIGGER_2021"
            self._logger.warning(f"⚠️ [{clean_sym}] Не вдалося виставити SL @ {sl_p}: {e}")
            return False, f"SL_FAILED:{e_str[:120]}"

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
            self._cancel_conditional_orders_sync(ccxt_sym, types_filter=("take_profit_market", "take_profit"))

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
            if self.is_symbol_chasing(clean):
                continue
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

    def _cancel_symbol_orders_with_sl_capture_sync(self, ccxt_sym: str, clean_sym: str) -> Tuple[bool, float]:
        """Скасовує всі відкриті та умовні ордери по символу і повертає (ok, stop_price_якщо_був_SL)."""
        if self._exchange is None:
            return False, 0.0
        captured_sl_px = 0.0
        for is_trig in (False, True):
            try:
                ords = (
                    self._exchange.fetch_open_orders(ccxt_sym, params={"trigger": True})
                    if is_trig
                    else self._exchange.fetch_open_orders(ccxt_sym)
                )
            except TypeError:
                if is_trig:
                    continue
                ords = self._exchange.fetch_open_orders(ccxt_sym)
            except Exception:
                continue
            if not isinstance(ords, (list, tuple)):
                continue
            for o in ords:
                if not isinstance(o, dict):
                    continue
                o_type = self._extract_order_type(o)
                if o_type in ("stop_market", "stop") and captured_sl_px <= 0.0:
                    sp = float(
                        o.get("stopPrice")
                        or o.get("triggerPrice")
                        or (o.get("info") or {}).get("stopPrice")
                        or (o.get("info") or {}).get("triggerPrice")
                        or 0.0
                    )
                    if sp > 0.0:
                        captured_sl_px = sp

        ok = False
        try:
            self._exchange.cancel_all_orders(ccxt_sym)
            ok = True
        except Exception as e:
            self._logger.warning(f"⚠️ [{clean_sym}] Помилка cancel_all_orders: {e}")
        try:
            if self._cancel_conditional_orders_sync(ccxt_sym) > 0:
                ok = True
        except Exception:
            pass
        return ok, captured_sl_px

    async def cancel_symbol_orders(self, symbol: str) -> bool:
        return await asyncio.to_thread(self._cancel_symbol_orders_sync, symbol)

    def _cancel_symbol_orders_sync(self, symbol: str) -> bool:
        clean = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean)
        ok, _ = self._cancel_symbol_orders_with_sl_capture_sync(ccxt_sym, clean)
        return ok

    async def fetch_all_open_orders_by_symbol(self, symbols: Tuple[str, ...]) -> Dict[str, List[Dict[str, Any]]]:
        """Повертає карту відкритих звичайних + Algo/Trigger ордерів по символах."""
        return await asyncio.to_thread(self._fetch_all_open_orders_by_symbol_sync, symbols)

    def _fetch_all_open_orders_by_symbol_sync(self, symbols: Tuple[str, ...]) -> Dict[str, List[Dict[str, Any]]]:
        if self._exchange is None:
            return {}
        out: Dict[str, List[Dict[str, Any]]] = {s.upper(): [] for s in symbols}
        bulk_ok = True
        has_bulk_algo_api = hasattr(self._exchange, "fapiPrivateGetOpenAlgoOrders") and not hasattr(self._exchange, "_mock_name")

        for is_trig in (False, True):
            try:
                if is_trig and has_bulk_algo_api:
                    # CCXT fetch_open_orders(None, params={'trigger': True}) повертає [] без symbol на Binance USD-M,
                    # тоді як fapiPrivateGetOpenAlgoOrders() повертає всі умовні STOP_MARKET/TP за 1 REST-запит!
                    algo_raw = self._exchange.fapiPrivateGetOpenAlgoOrders()
                    if isinstance(algo_raw, dict):
                        algo_raw = algo_raw.get("orders") or []
                    raw_ords = []
                    for r in (algo_raw or []):
                        if not isinstance(r, dict):
                            continue
                        trig_px = float(r.get("triggerPrice") or r.get("stopPrice") or 0.0)
                        raw_ords.append({
                            "id": str(r.get("algoId") or r.get("orderId") or ""),
                            "symbol": str(r.get("symbol") or ""),
                            "type": str(r.get("orderType") or r.get("origType") or r.get("type") or "").lower(),
                            "side": str(r.get("side") or "").lower(),
                            "stopPrice": trig_px,
                            "triggerPrice": trig_px,
                            "clientOrderId": str(r.get("clientAlgoId") or r.get("clientOrderId") or ""),
                            "info": r,
                        })
                else:
                    raw_ords = (
                        self._exchange.fetch_open_orders(None, params={"trigger": True})
                        if is_trig
                        else self._exchange.fetch_open_orders(None)
                    )
            except TypeError:
                if is_trig:
                    continue
                try:
                    raw_ords = self._exchange.fetch_open_orders(None)
                except Exception:
                    bulk_ok = False
                    break
            except Exception:
                bulk_ok = False
                break
            if not isinstance(raw_ords, (list, tuple)):
                bulk_ok = False
                break
            for o in raw_ords:
                if not isinstance(o, dict):
                    continue
                c_sym = ccxt_to_symbol(str(o.get("symbol") or (o.get("info") or {}).get("symbol") or ""))
                if c_sym in out:
                    out[c_sym].append(o)

        if bulk_ok:
            return out

        out = {s.upper(): [] for s in symbols}
        for s in symbols:
            clean = ccxt_to_symbol(s)
            ccxt_sym = symbol_to_ccxt(clean)
            if not self._is_listed_market(ccxt_sym):
                continue
            for is_trig in (False, True):
                try:
                    ords = (
                        self._exchange.fetch_open_orders(ccxt_sym, params={"trigger": True})
                        if is_trig
                        else self._exchange.fetch_open_orders(ccxt_sym)
                    )
                except TypeError:
                    if is_trig:
                        continue
                    ords = self._exchange.fetch_open_orders(ccxt_sym)
                except Exception:
                    continue
                if isinstance(ords, (list, tuple)):
                    out[clean].extend(o for o in ords if isinstance(o, dict))
        return out

    async def cleanup_orphan_orders(
        self, active_positions: Dict[str, float], candidate_symbols: Optional[Tuple[str, ...]] = None
    ) -> int:
        """Після кожного ребалансу прибирає осиротілі лімітні та Algo/Trigger SL/TP ордери на парах із нульовою позицією."""
        return await asyncio.to_thread(self._cleanup_orphan_orders_sync, active_positions, candidate_symbols)

    def _cleanup_orphan_orders_sync(
        self, active_positions: Dict[str, float], candidate_symbols: Optional[Tuple[str, ...]] = None
    ) -> int:
        if self._exchange is None:
            return 0
        syms = candidate_symbols or tuple(active_positions.keys())
        cleaned = 0
        for s in syms:
            clean = ccxt_to_symbol(s)
            if self.is_symbol_chasing(clean):
                continue
            min_q, _, _, _, _ = settings.get_symbol_spec(clean)
            if abs(float(active_positions.get(clean, 0.0) or 0.0)) >= min_q:
                continue
            ccxt_sym = symbol_to_ccxt(clean)
            if not self._is_listed_market(ccxt_sym):
                continue
            cleaned += self._cancel_conditional_orders_sync(ccxt_sym)
        return cleaned

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