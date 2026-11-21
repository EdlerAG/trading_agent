import time
import inspect
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import pandas as pd

from app.core.config import settings
from app.core.memory_guard import memory_guard
from app.domain.interfaces import IService, IExchangeGateway, IOnlineLearner
from app.services.state_service import StateService
from app.services.database_service import DatabaseService
from app.services.news_ai_service import NewsAiService
from app.cartridges.cartridge_loader import CartridgeLoaderService


class MultiAssetExecutionOrchestrator(IService):
    """
    Верховний Оркестратор Виконання (QuantCore V58.0 Pure SOTA Runner):
    - Керує кошиком із 5+ валют одночасно на єдиному ф'ючерсному рахунку USDT.
    - Фіксує спрацювання біржових стопів у SQLite та зберігає захист Breakeven при ребалансах.
    """

    __slots__ = (
        "_logger",
        "_state",
        "_db",
        "_exchange",
        "_cartridges",
        "_learner",
        "_news",
        "_market_data",
        "_governor",
        "_tg_sender",
        "_ws_sentinel",
        "_shadow_arena",
        "_last_backup_date",
        "_last_funding_poll_ts",
        "_demo_wallet_anchor",
    )

    def __init__(
        self,
        logger: logging.Logger,
        state_service: StateService,
        db_service: DatabaseService,
        exchange_service: IExchangeGateway,
        cartridge_service: CartridgeLoaderService,
        online_learner: IOnlineLearner,
        news_service: NewsAiService,
        market_data_service: Optional[Any] = None,
        currency_governor: Optional[Any] = None,
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._db = db_service
        self._exchange = exchange_service
        self._cartridges = cartridge_service
        self._learner = online_learner
        self._news = news_service
        self._market_data = market_data_service
        self._governor = currency_governor
        self._tg_sender = None
        self._ws_sentinel = None
        self._shadow_arena = None
        self._last_backup_date = datetime.now(timezone.utc).date()
        self._last_funding_poll_ts: float = 0.0
        self._demo_wallet_anchor: float = 0.0

    @property
    def name(self) -> str:
        return "MultiAssetExecutionOrchestrator"

    def bind_telegram_sender(self, tg_service) -> None:
        self._tg_sender = tg_service

    def bind_ws_sentinel(self, ws_sentinel) -> None:
        self._ws_sentinel = ws_sentinel

    def bind_shadow_arena(self, arena_service) -> None:
        self._shadow_arena = arena_service

    async def _send_alert(self, msg: str) -> None:
        if self._tg_sender is not None:
            await self._tg_sender.send_alert(msg)

    async def notify_error(self, err_text: str) -> None:
        await self._send_alert(f"⚠️ <b>Збій ітерації свічки:</b>\n<code>{err_text[:300]}</code>")

    async def init(self) -> None:
        self._state.sync_supported_symbols(self._cartridges.cartridge.supported_symbols)

    async def shutdown(self) -> None:
        pass

    async def emergency_close_all_positions(self) -> str:
        syms = tuple(self._state.coins.keys())
        report = await self._exchange.emergency_liquidate_all(syms)
        for c in self._state.coins.values():
            c.current_pos_qty = 0.0
            c.entry_price = 0.0
            c.active_sl_price = 0.0
            c.is_breakeven = False
            c.bars_held = 0
            c.phase = 0
        self._state.save_snapshot()
        await self._send_alert(report)
        return report

    async def _check_daily_circuit_breaker(self, total_equity: float) -> bool:
        if total_equity <= 0.0:
            return False
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._state.last_reset_date != today_str or self._state.daily_starting_equity <= 0.0:
            past_pnl = self._db.get_daily_realized_pnl()
            base_eq = total_equity - past_pnl if (total_equity - past_pnl) > 0 else total_equity
            self._state.daily_starting_equity = base_eq
            self._state.last_reset_date = today_str
            self._state.save_snapshot()

        start_eq = self._state.daily_starting_equity
        if start_eq > 0:
            dd = (start_eq - total_equity) / start_eq
            if dd >= settings.MAX_DAILY_LOSS_PCT and not self._state.is_paused:
                # Адаптивний 2-годинний кулдаун замість 24h повної зупинки
                self._state.set_pause_state(paused=True, hours=2.0)
                await self.emergency_close_all_positions()
                msg = (
                    f"🛑 <b>CIRCUIT BREAKER АКТИВОВАНО!</b>\n\n"
                    f"• Просадка доби: <b>{dd:.2%}</b> (ліміт: {settings.MAX_DAILY_LOSS_PCT:.0%})\n"
                    f"• Позиції закрито в кеш для зняття пікового ризику.\n"
                    f"• Автоматичне відновлення через <b>2 години</b> (або введіть /resume у будь-який момент)."
                )
                await self._send_alert(msg)
                return True
        return False

    async def _monitor_coin_breakeven(self, sym: str, current_price: float, atr_val: float) -> None:
        c = self._state.coins.get(sym)
        if not c or abs(c.current_pos_qty) <= 0.0 or c.entry_price <= 0.0 or c.is_breakeven or atr_val <= 0.0:
            return
        if getattr(c, "dominant_book", "") in ("B1_STATARB", "B2_CARRY_BASIS", "B5_KALMAN_PAIRS", "V2_MOMENTUM"):
            return

        be_dist = settings.ATR_BREAKEVEN_TRIGGER * atr_val
        trigger = False
        raw_be = 0.0

        if c.current_pos_qty > 0 and (current_price - c.entry_price) >= be_dist:
            trigger = True
            raw_be = c.entry_price * (1.0 + settings.BREAKEVEN_BUFFER_PCT)
        elif c.current_pos_qty < 0 and (c.entry_price - current_price) >= be_dist:
            trigger = True
            raw_be = c.entry_price * (1.0 - settings.BREAKEVEN_BUFFER_PCT)

        if trigger:
            ok = await self._exchange.place_or_update_stop_loss(sym, c.current_pos_qty, raw_be)
            if ok:
                c.is_breakeven = True
                c.active_sl_price = self._exchange.safe_price(sym, raw_be)
                self._state.save_snapshot()
                await self._send_alert(
                    f"🛡️ <b>[{sym}] Страховий Stop-Loss переведено в БЕЗЗБИТОК!</b>\n"
                    f"• Позиція: <code>{c.current_pos_qty:+.4f}</code> | Вхід: <code>${c.entry_price:,.4f}</code>\n"
                    f"• Новий Stop-Loss: <b>${c.active_sl_price:,.4f}</b> (Mark Price)"
                )

    async def run_step(self, force_recalc: bool = False) -> None:
        t0 = time.time()

        if self._state.check_and_auto_resume_pause():
            await self._send_alert("▶️ <b>Час паузи вичерпано!</b> QuantCore V58.0 відновив штатну торгівлю.")

        if self._state.force_step:
            force_recalc = True
            self._state.force_step = False

        if self._state.is_paused:
            self._logger.info("⏸️ Оркестратор на паузі. Пропуск свічки.")
            return

        today = datetime.now(timezone.utc).date()
        if today > self._last_backup_date:
            self._last_backup_date = today
            b_path = self._db.cleanup_old_records_and_backup()
            if b_path and self._tg_sender is not None:
                await self._tg_sender.send_document(b_path, caption=f"📦 Авто-бекап БД QuantCore ({today.strftime('%d.%m.%Y')})")

        cartridge = self._cartridges.cartridge
        self._state.active_cartridge = self._cartridges.active_name
        active_syms = cartridge.supported_symbols
        is_multi_sleeve_family = (
            settings.CARTRIDGE_ENGINE in ("v2", "v3", "v4", "v5")
            or "v2" in str(self._cartridges.active_name).lower()
            or "v3" in str(self._cartridges.active_name).lower()
            or "v4" in str(self._cartridges.active_name).lower()
            or "v5" in str(self._cartridges.active_name).lower()
            or "MultiSleeve" in getattr(cartridge, "architecture_name", "")
            or "Apex" in getattr(cartridge, "architecture_name", "")
            or "AllRegime" in getattr(cartridge, "architecture_name", "")
        )

        # 0. Скасування застарілих stink-bid ордерів ТІЛЬКИ для V58 (у V2/V3 економить 58 приватних REST-запитів щогодини!)
        if (not is_multi_sleeve_family) and hasattr(self._exchange, "cancel_all_stink_bids"):
            await self._exchange.cancel_all_stink_bids(active_syms)
        if self._ws_sentinel is not None:
            self._ws_sentinel.clear_stink_bids()

        # 1. Конкурентне завантаження свічок (для V2/V3 вимагаємо >=365 барів прогріву 360h фіч із фолбеком для коротких моків)
        req_min_bars = 365 if is_multi_sleeve_family else 200
        if self._market_data is not None:
            candles_map = await self._market_data.fetch_synchronized_candles(active_syms, min_bars=req_min_bars)
            if not candles_map and req_min_bars > 200:
                candles_map = await self._market_data.fetch_synchronized_candles(active_syms, min_bars=200)
        else:
            candles_map = {}
            for sym in active_syms:
                df = await self._exchange.fetch_delta_candles(sym, limit=settings.effective_candles_limit)
                if df is not None and len(df) >= 200:
                    candles_map[sym] = df

        if "BTCUSDT" not in candles_map:
            self._logger.warning("⚠️ Недостатньо свічок для BTCUSDT. Очікування наступної ітерації.")
            return

        btc_df = candles_map["BTCUSDT"]
        candle_ts = str(btc_df["timestamp"].iloc[-1])

        # Data Staleness Guard (тільки при реальному ccxt шлюзі, а не тестових моках з історичними свічками)
        raw_ccxt = getattr(self._exchange, "_exchange", None)
        if raw_ccxt is not None and not hasattr(raw_ccxt, "_mock_name") and not hasattr(self._exchange, "_mock_name") and "open_ms" in btc_df.columns:
            last_open_ms = int(btc_df["open_ms"].iloc[-1])
            age_sec = time.time() - (last_open_ms / 1000.0)
            max_age_sec = float(settings.CANDLE_INTERVAL_MINUTES) * 60.0 * float(settings.MAX_CANDLE_STALENESS_MULT)
            if age_sec > max_age_sec:
                self._logger.warning(f"⚠️ Застарілі ринкові дані BTCUSDT (вік свічки {age_sec/60:.1f} хв > ліміту). Пропуск торгів!")
                await self._send_alert(f"⚠️ <b>[Staleness Guard]</b> Свічка BTCUSDT застаріла ({age_sec/60:.0f} хв). Торговий крок пропущено.")
                return

        is_new_candle = (candle_ts != self._state.last_candle_ts)
        if not force_recalc and not is_new_candle:
            return

        # 2. Синхронізація фактичного балансу та позицій з біржею Binance Futures (+ VIRTUAL_EQUITY_CAP для Testnet $500!)
        usdt_balance, total_upnl, ex_positions, is_sync_ok = await self._exchange.fetch_account_snapshot(active_syms)
        if not is_sync_ok or usdt_balance <= 0.0:
            self._logger.warning("⚠️ Тимчасовий збій синхронізації балансу. Пропуск ребалансу без скидання ордерів.")
            return

        if settings.USE_DEMO_TRADING and settings.VIRTUAL_EQUITY_CAP > 0.0:
            raw_demo_eq = float(usdt_balance) + float(total_upnl)
            if self._demo_wallet_anchor <= 0.0:
                self._demo_wallet_anchor = raw_demo_eq
            demo_net_delta = raw_demo_eq - self._demo_wallet_anchor
            total_equity = max(10.0, float(settings.VIRTUAL_EQUITY_CAP) + demo_net_delta)
        else:
            total_equity = max(10.0, usdt_balance + total_upnl)

        coin_prices: Dict[str, float] = {}
        coin_upnl: Dict[str, float] = {}

        for sym in active_syms:
            df_s = candles_map.get(sym)
            cur_p = float(df_s["close"].iloc[-1]) if df_s is not None else 0.0
            coin_prices[sym] = cur_p

            ex_p = ex_positions.get(sym)
            c_st = self._state.coins.get(sym)
            if c_st is None:
                continue

            real_qty = ex_p.contracts_qty if ex_p else 0.0
            coin_upnl[sym] = ex_p.unrealized_pnl if ex_p else 0.0
            min_qty, _, _, _, _ = settings.get_symbol_spec(sym)

            # Якщо біржа закрила позицію по Stop-Loss між свічками — фіксуємо PnL у БД та сповіщаємо!
            if abs(real_qty) < min_qty and abs(c_st.current_pos_qty) >= min_qty:
                if hasattr(self._exchange, "sync_exchange_stop_closure"):
                    sl_info = await self._exchange.sync_exchange_stop_closure(sym)
                    if sl_info:
                        closed_q, avg_p, r_pnl = sl_info
                        if r_pnl >= 0.0:
                            await self._send_alert(
                                f"🎯 <b>[{sym}] Фіксація прибутку (Take-Profit / MFE)!</b>\n"
                                f"• Закрито: <code>{closed_q:.4f}</code> @ <code>${avg_p:,.4f}</code>\n"
                                f"• Фіксований PnL: <b>+{r_pnl:.2f} USDT</b>"
                            )
                        else:
                            await self._send_alert(
                                f"🛡️ <b>[{sym}] Спрацював біржовий Stop-Loss!</b>\n"
                                f"• Закрито: <code>{closed_q:.4f}</code> @ <code>${avg_p:,.4f}</code>\n"
                                f"• Фіксований PnL: <b>{r_pnl:+.2f} USDT</b>"
                            )
                c_st.current_pos_qty = 0.0
                c_st.entry_price = 0.0
                c_st.active_sl_price = 0.0
                c_st.is_breakeven = False
                c_st.bars_held = 0
            elif abs(real_qty) >= min_qty:
                c_st.current_pos_qty = real_qty
                if ex_p and ex_p.entry_price > 0:
                    c_st.entry_price = ex_p.entry_price
                if is_new_candle:
                    c_st.bars_held += 1

        if await self._check_daily_circuit_breaker(total_equity):
            return

        # 3. Оцінка новинного фону Gemini AI (Macro + Per-Asset Bias + Geo-Macro Shock) та фандінгу
        news_intel = await self._news.fetch_market_intelligence()
        news_score = float(news_intel.get("macro_sentiment", 0.0))
        geo_shock_active = bool(news_intel.get("is_geo_shock", False))
        coin_bias_map = news_intel.get("coin_bias", {})
        funding_rates_map = await self._exchange.fetch_funding_rates(active_syms)

        if geo_shock_active:
            self._logger.warning(
                f"🚨 [R5: GEO-MACRO SHOCK] Активовано екстрений захист від системного шоку! "
                f"(geo_shock_prob={self._news.geo_shock_prob:.2f})"
            )

        # 4. Запуск ШІ-картриджа для розрахунку цільового портфеля
        online_states = self._learner.get_all_learning_states()
        _cpt_sig = inspect.signature(cartridge.compute_portfolio_targets).parameters
        _cpt_kwargs = {"account_equity": total_equity} if "account_equity" in _cpt_sig else {}
        portfolio_dto = await asyncio.to_thread(
            cartridge.compute_portfolio_targets,
            candles_map,
            self._state.coins,
            online_states,
            self._state.max_portfolio_lev,
            self._state.orchestrator_mode,
            news_score,
            funding_rates_map,
            geo_shock_active,
            coin_bias_map,
            **_cpt_kwargs,
        )

        # Синхронізація лімітів та налаштувань монет через Currency Governor
        if self._governor is not None:
            portfolio_dto = self._governor.enforce_currency_rules(portfolio_dto)

        # 5. Двофазна паралельна диспетчеризація ордерів (Фаза А: Звільнення маржі, Фаза Б: Нарощування)
        is_v2_engine = (
            getattr(portfolio_dto, "cartridge_name", "") in ("v2_multi_sleeve", "v3_multi_sleeve", "v4_multi_sleeve", "v5_multi_sleeve")
            or settings.CARTRIDGE_ENGINE in ("v2", "v3", "v4", "v5")
        )
        extra_tel = portfolio_dto.extra_telemetry or {}
        sleeve_books_map: Dict[str, str] = extra_tel.get("sleeve_books") or {}
        signal_prices_map: Dict[str, float] = extra_tel.get("signal_prices") or extra_tel.get("prices") or {}
        skipped_exec: Dict[str, str] = {}

        executed_orders_summary: List[str] = []
        coin_targets_map: Dict[str, float] = {}
        if self._ws_sentinel is not None:
            self._ws_sentinel.clear_stink_bids()
            self._ws_sentinel.update_symbol_atrs(
                {s: t.atr_14 for s, t in portfolio_dto.targets.items() if t.atr_14 > 0}
            )

        _exec_sig_params = inspect.signature(self._exchange.execute_smart_rebalance_order).parameters
        _exec_has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _exec_sig_params.values())

        async def _execute_single_order_plan(plan: Dict[str, Any]) -> Optional[str]:
            sym = plan["sym"]
            delta_qty = plan["delta_qty"]
            cur_p = plan["cur_p"]
            cur_atr = plan["cur_atr"]
            pnl_est = plan["pnl_est"]
            note_str = plan["note_str"]
            reduce_only = plan["reduce_only"]
            desired_w = plan["desired_w"]
            is_closing_to_cash = plan["is_closing_to_cash"]
            is_opening_from_cash = plan["is_opening_from_cash"]
            is_flip = plan["is_flip"]
            sleeve_book_tag = str(plan.get("sleeve_book") or sleeve_books_map.get(sym) or plan.get("dominant_book") or "SLEEVE_B")
            sig_px = float(signal_prices_map.get(sym, cur_p) or cur_p)

            c_st = self._state.coins.get(sym)
            if c_st is None:
                return None

            min_qty, _, _, _, _ = settings.get_symbol_spec(sym)

            if reduce_only or is_closing_to_cash or is_flip:
                await self._exchange.cancel_symbol_orders(sym)

            ord_kwargs: Dict[str, Any] = {
                "symbol": sym,
                "delta_qty": delta_qty,
                "mark_price": cur_p,
                "realized_pnl_est": pnl_est,
                "note": note_str,
                "reduce_only": reduce_only,
            }
            if "maker_first" in _exec_sig_params or _exec_has_varkw:
                ord_kwargs["maker_first"] = bool(plan.get("maker_first", False))
            if ("taker_fallback" in _exec_sig_params or _exec_has_varkw) and plan.get("taker_fallback") is not None:
                ord_kwargs["taker_fallback"] = bool(plan.get("taker_fallback"))
            if "urgency" in _exec_sig_params and plan.get("urgency"):
                ord_kwargs["urgency"] = str(plan["urgency"])
            ord_dto = await self._exchange.execute_smart_rebalance_order(**ord_kwargs)

            if ord_dto is None:
                if is_v2_engine and hasattr(self._db, "record_v2_execution"):
                    diag = self._exchange.get_last_order_diag(sym) if hasattr(self._exchange, "get_last_order_diag") else {}
                    diag = diag if isinstance(diag, dict) else {}
                    self._db.record_v2_execution(
                        candle_ts=candle_ts,
                        symbol=sym,
                        sleeve_book=sleeve_book_tag,
                        side="BUY" if delta_qty > 0 else "SELL",
                        target_qty=abs(float(delta_qty)),
                        executed_qty=0.0,
                        signal_close_px=sig_px,
                        arrival_mid_px=float(diag.get("arrival_mid_px", cur_p) or cur_p),
                        fill_avg_px=0.0,
                        spread_bps=float(diag.get("spread_bps", 0.0) or 0.0),
                        maker_qty=0.0,
                        taker_qty=0.0,
                        fee_usdt=0.0,
                        latency_ms=float(diag.get("latency_ms", 0.0) or 0.0),
                        order_status=str(diag.get("order_status") or "REJECTED"),
                    )
                self._logger.warning(f"⚠️ [{sym}] Ордер ребалансу не виконано біржею (пропуск до наступної свічки).")
                return None

            if is_v2_engine and hasattr(self._db, "record_v2_execution"):
                arr_px = float(getattr(ord_dto, "arrival_mid_px", 0.0) or getattr(ord_dto, "arrival_price", 0.0) or cur_p)
                mk_q = float(getattr(ord_dto, "maker_qty", 0.0) or 0.0)
                tk_q = float(getattr(ord_dto, "taker_qty", 0.0) or 0.0)
                if mk_q <= 0.0 and tk_q <= 0.0:
                    # Для mock/зовнішніх шлюзів без розбивки maker_qty/taker_qty
                    if bool(getattr(ord_dto, "is_maker", False)):
                        mk_q = float(ord_dto.executed_qty)
                    else:
                        tk_q = float(ord_dto.executed_qty)
                self._db.record_v2_execution(
                    candle_ts=candle_ts,
                    symbol=sym,
                    sleeve_book=sleeve_book_tag,
                    side=str(ord_dto.side),
                    target_qty=abs(float(delta_qty)),
                    executed_qty=float(ord_dto.executed_qty),
                    signal_close_px=sig_px,
                    arrival_mid_px=arr_px,
                    fill_avg_px=float(ord_dto.avg_price),
                    spread_bps=float(getattr(ord_dto, "spread_bps", 0.0) or 0.0),
                    maker_qty=mk_q,
                    taker_qty=tk_q,
                    fee_usdt=float(getattr(ord_dto, "fee_usdt", 0.0) or 0.0),
                    latency_ms=float(getattr(ord_dto, "latency_ms", 0.0) or 0.0),
                    order_status=str(getattr(ord_dto, "order_status", "FILLED") or "FILLED"),
                )

            old_qty = c_st.current_pos_qty
            signed_exec = ord_dto.executed_qty if ord_dto.side == "BUY" else -ord_dto.executed_qty
            new_pos_qty = 0.0 if is_closing_to_cash else (old_qty + signed_exec)

            if abs(new_pos_qty) >= min_qty:
                if is_opening_from_cash or is_flip:
                    c_st.entry_price = ord_dto.avg_price
                    c_st.bars_held = 1
                    c_st.is_breakeven = False
                elif (old_qty * signed_exec) > 0.0 and c_st.entry_price > 0.0:
                    c_st.entry_price = (
                        (abs(old_qty) * c_st.entry_price) + (ord_dto.executed_qty * ord_dto.avg_price)
                    ) / max(1e-8, abs(new_pos_qty))

                c_st.current_pos_qty = new_pos_qty
                dom_b = str(plan.get("dominant_book", getattr(c_st, "dominant_book", "")) or "")
                sl_mult = float(plan.get("sl_atr_mult", getattr(c_st, "sl_atr_mult", 0.0)) or 0.0)
                tp_mult = float(plan.get("tp_atr_mult", getattr(c_st, "tp_atr_mult", 0.0)) or 0.0)
                c_st.dominant_book = dom_b
                c_st.sl_atr_mult = sl_mult
                c_st.tp_atr_mult = tp_mult

                # Якщо вже був активований Breakeven — зберігаємо беззбитковий стоп!
                if dom_b == "V2_MOMENTUM":
                    # V2-рукав тримає позицію до 14-денного ребалансу і не має
                    # біржового стопу: інакше 1.35 ATR(1h) вибиває книгу за години.
                    c_st.active_sl_price = 0.0
                    sl_note = "SL: None (Model-Exit)"
                else:
                    if c_st.is_breakeven and c_st.entry_price > 0.0:
                        raw_sl = (
                            c_st.entry_price * (1.0 + settings.BREAKEVEN_BUFFER_PCT)
                            if new_pos_qty > 0
                            else c_st.entry_price * (1.0 - settings.BREAKEVEN_BUFFER_PCT)
                        )
                    else:
                        eff_sl_mult = sl_mult if sl_mult > 0.0 else settings.EMERGENCY_SL_ATR_MULT
                        sl_dist = eff_sl_mult * cur_atr
                        raw_sl = (c_st.entry_price - sl_dist) if new_pos_qty > 0 else (c_st.entry_price + sl_dist)

                    sl_p = self._exchange.safe_price(sym, raw_sl)
                    c_st.active_sl_price = sl_p
                    await self._exchange.place_or_update_stop_loss(sym, new_pos_qty, sl_p)
                    sl_note = f"SL: <code>${sl_p:,.2f}</code>"

                # Book-Aware Take-Profit: B1/B2/B5/V2 hold-books exit via model/rebalance, NOT tight 1.35 ATR TP
                is_mean_rev_book = dom_b in ("B1_STATARB", "B2_CARRY_BASIS", "B5_KALMAN_PAIRS", "V2_MOMENTUM")
                if is_mean_rev_book and tp_mult <= 0.0:
                    tp_note = "TP: Model-Exit"
                else:
                    eff_tp_mult = tp_mult if tp_mult > 0.0 else settings.SUB_CANDLE_MFE_ATR_MULT
                    tp_dist = eff_tp_mult * cur_atr
                    raw_tp = (c_st.entry_price + tp_dist) if new_pos_qty > 0 else (c_st.entry_price - tp_dist)
                    tp_p = self._exchange.safe_price(sym, raw_tp)
                    if hasattr(self._exchange, "place_or_update_take_profit"):
                        await self._exchange.place_or_update_take_profit(sym, new_pos_qty, tp_p)
                    tp_note = f"TP: <code>${tp_p:,.2f}</code>"

                icon = "🟢" if ord_dto.side == "BUY" else "🔴"
                return (
                    f"{icon} <b>{sym}</b>: {ord_dto.side} <code>{ord_dto.executed_qty}</code> @ <code>${ord_dto.avg_price:,.2f}</code> "
                    f"➔ <b>{desired_w:+.2f}x</b> ({sl_note} | {tp_note})"
                )
            else:
                c_st.current_pos_qty = 0.0
                c_st.entry_price = 0.0
                c_st.active_sl_price = 0.0
                c_st.is_breakeven = False
                c_st.bars_held = 0
                c_st.dominant_book = ""
                c_st.sl_atr_mult = 0.0
                c_st.tp_atr_mult = 0.0
                if hasattr(self._exchange, "cancel_symbol_orders"):
                    await self._exchange.cancel_symbol_orders(sym)
                return f"⚪ <b>{sym}</b>: Вихід у КЕШ @ <code>${ord_dto.avg_price:,.2f}</code> (PnL: <b>{pnl_est:+.2f}$</b>)"

        phase_a_plans: List[Dict[str, Any]] = []
        phase_b_plans: List[Dict[str, Any]] = []

        for sym, target_dto in portfolio_dto.targets.items():
            c_st = self._state.coins.get(sym)
            if c_st is None:
                continue

            cur_p = target_dto.current_price
            cur_atr = target_dto.atr_14
            coin_targets_map[sym] = target_dto.desired_weight

            if is_new_candle and not is_v2_engine:
                new_mwu = self._learner.record_step_and_adapt(
                    symbol=sym,
                    prev_price=0.0,
                    curr_price=cur_p,
                    prev_model_pos=c_st.last_signal,
                    tier_role=c_st.tier_role,
                    new_submodel_preds=target_dto.raw_submodel_preds,
                )
                c_st.mwu_trust = new_mwu

            c_st.phase = target_dto.phase
            c_st.last_signal = target_dto.raw_model_pos
            c_st.alpha_score = target_dto.alpha_score
            c_st.dominant_book = str(getattr(target_dto, "dominant_book", "") or "")
            c_st.sl_atr_mult = float(getattr(target_dto, "sl_atr_mult", 0.0) or 0.0)
            c_st.tp_atr_mult = float(getattr(target_dto, "tp_atr_mult", 0.0) or 0.0)

            await self._monitor_coin_breakeven(sym, cur_p, cur_atr)

            min_qty, _, min_notional, _, _ = settings.get_symbol_spec(sym)
            cur_weight = (c_st.current_pos_qty * cur_p) / total_equity if total_equity > 0 else 0.0
            if not (c_st.enabled and c_st.mode != 0):
                desired_w = 0.0
                if abs(target_dto.desired_weight) >= settings.CASH_ZONE_THRESHOLD:
                    skipped_exec[sym] = "disabled_mode"
            else:
                desired_w = target_dto.desired_weight

            is_v2_book = is_v2_engine or (c_st.dominant_book == "V2_MOMENTUM")
            is_closing_to_cash = abs(desired_w) < settings.CASH_ZONE_THRESHOLD
            is_opening_from_cash = abs(cur_weight) < settings.CASH_ZONE_THRESHOLD and abs(desired_w) >= settings.CASH_ZONE_THRESHOLD
            is_flip = (cur_weight * desired_w) < 0.0
            weight_diff = abs(desired_w - cur_weight)
            s_book_lbl = str(sleeve_books_map.get(sym) or ("V2_MOMENTUM" if is_v2_book else c_st.dominant_book))

            if not is_v2_book:
                if not (is_closing_to_cash or is_opening_from_cash or is_flip) and weight_diff < settings.ACTION_DEADZONE:
                    continue

            if is_closing_to_cash:
                if abs(c_st.current_pos_qty) < min_qty:
                    continue
                delta_qty = -c_st.current_pos_qty
                pnl_est = coin_upnl.get(sym, 0.0)
                note_str = (
                    f"V2 Exit ({s_book_lbl} | Score:{target_dto.alpha_score:+.2f})"
                    if is_v2_book
                    else f"Exit to Cash (F0 | Score:{target_dto.alpha_score:+.2f})"
                )
                phase_a_plans.append({
                    "sym": sym,
                    "delta_qty": delta_qty,
                    "cur_p": cur_p,
                    "cur_atr": cur_atr,
                    "pnl_est": pnl_est,
                    "note_str": note_str,
                    "reduce_only": True,
                    "desired_w": desired_w,
                    "is_closing_to_cash": True,
                    "is_opening_from_cash": False,
                    "is_flip": False,
                    "dominant_book": c_st.dominant_book,
                    "sleeve_book": s_book_lbl,
                    "sl_atr_mult": c_st.sl_atr_mult,
                    "tp_atr_mult": c_st.tp_atr_mult,
                    "maker_first": is_v2_book,
                    "taker_fallback": True if is_v2_book else None,
                })
            else:
                target_usdt = total_equity * desired_w
                target_qty_raw = target_usdt / max(1e-8, cur_p)
                target_qty = self._exchange.safe_amount(sym, abs(target_qty_raw))
                if target_qty < min_qty or (target_qty * cur_p) < min_notional:
                    skipped_exec[sym] = "lot_filter"
                    continue
                if desired_w < 0:
                    target_qty = -target_qty
                delta_qty = target_qty - c_st.current_pos_qty

                if is_v2_book:
                    v2_min_delta_usd = max(5.0, 0.015 * total_equity)
                    v2_rel_thresh_usd = 0.18 * abs(c_st.current_pos_qty) * cur_p
                    if abs(delta_qty) * cur_p < max(v2_min_delta_usd, v2_rel_thresh_usd):
                        skipped_exec[sym] = "deadzone"
                        continue

                if abs(delta_qty) < min_qty or (abs(delta_qty) * cur_p) < min_notional:
                    skipped_exec[sym] = "min_notional"
                    continue
                is_partial_trim = (c_st.current_pos_qty * delta_qty) < 0.0 and not is_flip
                note_str = (
                    f"V2 {s_book_lbl} ({desired_w:+.3f}x | Score:{target_dto.alpha_score:+.2f})"
                    if is_v2_book
                    else f"V58 Phase {target_dto.phase} ({desired_w:+.2f}x | MWU:{c_st.mwu_trust:.2f}x)"
                )

                if is_partial_trim:
                    trim_ratio = min(1.0, abs(delta_qty) / max(1e-8, abs(c_st.current_pos_qty)))
                    pnl_est = coin_upnl.get(sym, 0.0) * trim_ratio
                    phase_a_plans.append({
                        "sym": sym,
                        "delta_qty": delta_qty,
                        "cur_p": cur_p,
                        "cur_atr": cur_atr,
                        "pnl_est": pnl_est,
                        "note_str": note_str,
                        "reduce_only": True,
                        "desired_w": desired_w,
                        "is_closing_to_cash": False,
                        "is_opening_from_cash": False,
                        "is_flip": False,
                        "dominant_book": c_st.dominant_book,
                        "sleeve_book": s_book_lbl,
                        "sl_atr_mult": c_st.sl_atr_mult,
                        "tp_atr_mult": c_st.tp_atr_mult,
                        "maker_first": is_v2_book,
                        "taker_fallback": True if is_v2_book else None,
                    })
                else:
                    pnl_est = 0.0
                    urg_val = "high" if ("C" in s_book_lbl and is_v2_book) else ("low" if is_v2_book else "normal")
                    # Funding-Settlement Clock Guard (за 7 хв до 00/04/08/12/16/20 UTC):
                    # уникаємо миттєвої сплати високого фандінгу перед відсічкою і прискорюємо вхід, якщо фандінг платять НАМ!
                    if raw_ccxt is not None and not hasattr(raw_ccxt, "_mock_name") and not hasattr(self._exchange, "_mock_name"):
                        now_u = datetime.now(timezone.utc)
                        if now_u.hour in (3, 7, 11, 15, 19, 23) and now_u.minute >= 53:
                            fr_s = float((funding_rates_map or {}).get(sym, 0.0) or 0.0)
                            pays_heavy = (delta_qty > 0 and fr_s > 0.00025) or (delta_qty < 0 and fr_s < -0.00025)
                            earns_heavy = (delta_qty < 0 and fr_s > 0.00025) or (delta_qty > 0 and fr_s < -0.00025)
                            if pays_heavy and urg_val != "high":
                                skipped_exec[sym] = "funding_clock_defer"
                                continue
                            if earns_heavy:
                                urg_val = "high"
                    phase_b_plans.append({
                        "sym": sym,
                        "delta_qty": delta_qty,
                        "cur_p": cur_p,
                        "cur_atr": cur_atr,
                        "pnl_est": pnl_est,
                        "note_str": note_str,
                        "reduce_only": False,
                        "desired_w": desired_w,
                        "is_closing_to_cash": False,
                        "is_opening_from_cash": is_opening_from_cash,
                        "is_flip": is_flip,
                        "dominant_book": c_st.dominant_book,
                        "sleeve_book": s_book_lbl,
                        "sl_atr_mult": c_st.sl_atr_mult,
                        "tp_atr_mult": c_st.tp_atr_mult,
                        "maker_first": (
                            is_v2_book
                            or (
                                c_st.dominant_book in ("B1_STATARB", "B2_CARRY_BASIS", "B5_KALMAN_PAIRS")
                                and not is_flip
                            )
                        ),
                        "taker_fallback": True if is_v2_book else None,
                        "urgency": urg_val,
                    })

        # --- ДВОФАЗНА ПАРАЛЕЛЬНА ДИСПЕТЧЕРИЗАЦІЯ ---
        # Фаза А: Паралельне закриття / скорочення позицій (миттєве вивільнення USDT)
        if phase_a_plans:
            results_a = await asyncio.gather(
                *[_execute_single_order_plan(p) for p in phase_a_plans],
                return_exceptions=True,
            )
            for res in results_a:
                if isinstance(res, str):
                    executed_orders_summary.append(res)
                elif isinstance(res, Exception):
                    self._logger.error(f"❌ Помилка ордера Фази А: {res}")

        # Фаза Б: Паралельне відкриття нових або нарощування позицій на звільнену маржу
        if phase_b_plans:
            results_b = await asyncio.gather(
                *[_execute_single_order_plan(p) for p in phase_b_plans],
                return_exceptions=True,
            )
            for res in results_b:
                if isinstance(res, str):
                    executed_orders_summary.append(res)
                elif isinstance(res, Exception):
                    self._logger.error(f"❌ Помилка ордера Фази Б: {res}")

        # 5b. Post-Trade Neutrality Imbalance Guard (захист $500 від "голого" перекосу при частковому відхиленні ордера біржею)
        if is_v2_engine and (phase_a_plans or phase_b_plans) and total_equity > 0:
            realized_net_w = sum(
                (float(c.current_pos_qty) * float(coin_prices.get(s, 0.0))) / total_equity
                for s, c in self._state.coins.items()
                if abs(c.current_pos_qty) > 0
            )
            signed_target_net = sum(float(t.desired_weight) for t in portfolio_dto.targets.values())
            imbalance_w = realized_net_w - signed_target_net
            if abs(imbalance_w) > settings.NEUTRALITY_IMBALANCE_LIMIT:
                # Підрізаємо найбільшу позицію на боці надлишкового перекосу (reduce_only=True)
                excess_side = 1 if imbalance_w > 0 else -1
                cands_trim = [
                    (abs(c.current_pos_qty) * float(coin_prices.get(s, 0.0)), s, c)
                    for s, c in self._state.coins.items()
                    if (c.current_pos_qty > 0 and excess_side > 0) or (c.current_pos_qty < 0 and excess_side < 0)
                ]
                if cands_trim:
                    cands_trim.sort(reverse=True)
                    _not, sym_t, c_trim = cands_trim[0]
                    px_t = float(coin_prices.get(sym_t, 0.0))
                    min_q_t, _, _, _, _ = settings.get_symbol_spec(sym_t)
                    trim_usd = min(_not, abs(imbalance_w) * 0.65 * total_equity)
                    trim_q = self._exchange.safe_amount(sym_t, trim_usd / max(px_t, 1e-8))
                    if trim_q >= min_q_t:
                        signed_trim = -trim_q if excess_side > 0 else trim_q
                        self._logger.warning(
                            f"🛡️ [NeutralityGuard] Перекіс {imbalance_w:+.2f}x після ребалансу -> "
                            f"скорочення {sym_t} на {signed_trim:+.4f} (reduceOnly)."
                        )
                        fix_dto = await self._exchange.execute_smart_rebalance_order(
                            symbol=sym_t, delta_qty=signed_trim, mark_price=px_t,
                            realized_pnl_est=0.0, note="Neutrality Imbalance Guard", reduce_only=True,
                        )
                        if fix_dto is not None:
                            d_exec = fix_dto.executed_qty if fix_dto.side == "BUY" else -fix_dto.executed_qty
                            c_trim.current_pos_qty += d_exec
                            if abs(c_trim.current_pos_qty) < min_q_t:
                                c_trim.current_pos_qty = 0.0

        # 5b-legacy. Pillar 7: Margin-Backed Stink-Bids & VWAP Dip Sniper (ВИКЛЮЧНО для V58; у V2/V3 вимкнено для Zero Skew!)
        rem_lev_budget = max(0.0, self._state.max_portfolio_lev - portfolio_dto.total_gross_leverage)
        if (not is_v2_engine) and rem_lev_budget >= 0.40 and hasattr(self._exchange, "place_passive_stink_bid"):
            top_sym = portfolio_dto.extra_telemetry.get("top_leader")
            if top_sym and top_sym in portfolio_dto.targets and portfolio_dto.targets[top_sym].desired_weight > 0:
                t_info = portfolio_dto.targets[top_sym]
                stink_p = t_info.current_price - 2.20 * t_info.atr_14
                stink_usdt = total_equity * min(0.35, rem_lev_budget * 0.5)
                stink_qty = stink_usdt / max(1e-8, stink_p)
                min_q, _, min_not, _, _ = settings.get_symbol_spec(top_sym)
                if stink_qty >= min_q and (stink_qty * stink_p) >= min_not:
                    stink_ord_id = await self._exchange.place_passive_stink_bid(top_sym, stink_qty, stink_p)
                    if self._ws_sentinel is not None:
                        self._ws_sentinel.register_stink_bid(top_sym, stink_qty, stink_p, t_info.atr_14, order_id=stink_ord_id)

        # 5c. Трек A: Повна телеметрія та аудит-логи Testnet V2 (v2_decisions, v2_funding_ledger, v2_market_micro)
        if is_v2_engine:
            if hasattr(self._db, "record_v2_decision") and (is_new_candle or force_recalc):
                self._db.record_v2_decision(
                    candle_ts=candle_ts,
                    equity=total_equity,
                    wallet_balance=usdt_balance,
                    upnl=total_upnl,
                    extra_telemetry=extra_tel,
                    skipped_exec=skipped_exec,
                )

            now_wall = time.time()
            fn_income = getattr(self._exchange, "fetch_funding_income", None)
            if (
                callable(fn_income)
                and inspect.iscoroutinefunction(fn_income)
                and hasattr(self._db, "record_v2_funding_batch")
                and (is_new_candle or (now_wall - self._last_funding_poll_ts) >= 3300.0)
            ):
                try:
                    since_ms = int((now_wall - 48 * 3600.0) * 1000)
                    f_events = await fn_income(since_ms=since_ms)
                    if f_events:
                        pos_qty_now = {s: float(c.current_pos_qty) for s, c in self._state.coins.items()}
                        self._db.record_v2_funding_batch(f_events, pos_qty_now, funding_rates_map or {})
                    self._last_funding_poll_ts = now_wall
                except Exception as fe:
                    self._logger.debug(f"[V2] Помилка опитування funding income: {fe}")

            fn_micro = getattr(self._exchange, "fetch_market_microstructure", None)
            micro_snap: Dict[str, Dict[str, float]] = {}
            did_rebalance = bool(extra_tel.get("any_rebalanced", extra_tel.get("b_rebalanced", False))) or bool(phase_a_plans) or bool(phase_b_plans)
            if (
                did_rebalance
                and callable(fn_micro)
                and inspect.iscoroutinefunction(fn_micro)
                and hasattr(self._db, "record_v2_market_micro")
            ):
                try:
                    micro_snap = await fn_micro(active_syms)
                    if micro_snap:
                        self._db.record_v2_market_micro(candle_ts, micro_snap)
                except Exception as me:
                    self._logger.debug(f"[V2] Помилка збору market_micro: {me}")
        else:
            micro_snap = {}

        # 5d. Shadow Arena: паралельне оцінювання 6 моделей/тірів на тих самих живих свічках і спредах!
        arena_board: List[Dict[str, Any]] = []
        if self._shadow_arena is not None and settings.ENABLE_SHADOW_ARENA and (is_new_candle or force_recalc):
            try:
                sp_map = {s: float(m.get("spread_bps", 0.0)) for s, m in (micro_snap or {}).items()}
                arena_board = await asyncio.to_thread(
                    self._shadow_arena.step_all,
                    candle_ts,
                    candles_map,
                    coin_prices,
                    funding_rates_map or {},
                    coin_bias_map,
                    sp_map,
                )
            except Exception as ae:
                self._logger.debug(f"[ShadowArena] Step skipped: {ae}")

        # 6. Збереження телеметрії, стану та SQLite зрізу
        if not is_v2_engine:
            self._learner.save_state()
        calc_ms = round((time.time() - t0) * 1000.0, 1)
        active_coins_cnt = sum(1 for c in self._state.coins.values() if abs(c.current_pos_qty) > 0)

        self._state.last_candle_ts = candle_ts
        self._state.latest_telemetry = {
            "timestamp": candle_ts,
            "calc_ms": calc_ms,
            "engine_mode": settings.CARTRIDGE_ENGINE if settings.CARTRIDGE_ENGINE in ("v2", "v3", "v4", "v5") else ("v2" if is_v2_engine else "v58"),
            "wallet_balance": round(usdt_balance, 2),
            "unrealized_pnl": round(total_upnl, 2),
            "total_equity": round(total_equity, 2),
            "gross_leverage": portfolio_dto.total_gross_leverage,
            "net_leverage": portfolio_dto.net_leverage,
            "market_breadth": portfolio_dto.market_breadth,
            "cs_dispersion": float(extra_tel.get("cs_dispersion", 0.0) or 0.0),
            "btc_trend": float(extra_tel.get("btc_trend", 0.0) or 0.0),
            "tier": int(extra_tel.get("tier", 1) or 1),
            "a_gross": float(extra_tel.get("a_gross", 0.0) or 0.0),
            "b_gross": float(extra_tel.get("b_gross", 0.0) or 0.0),
            "c_gross": float(extra_tel.get("c_gross", 0.0) or 0.0),
            "d_gross": float(extra_tel.get("d_gross", 0.0) or 0.0),
            "e_gross": float(extra_tel.get("e_gross", 0.0) or 0.0),
            "virtual_equity_cap": float(settings.VIRTUAL_EQUITY_CAP) if settings.USE_DEMO_TRADING else 0.0,
            "b_rebalanced": bool(extra_tel.get("any_rebalanced", extra_tel.get("b_rebalanced", False))),
            "news_sentiment": portfolio_dto.news_sentiment,
            "geo_shock_active": geo_shock_active,
            "geo_shock_prob": self._news.geo_shock_prob,
            "active_coins_count": active_coins_cnt,
            "top_leader": portfolio_dto.extra_telemetry.get("top_leader", "BTCUSDT"),
            "coin_prices": coin_prices,
            "coin_upnl": coin_upnl,
            "coin_targets": coin_targets_map,
            "model_targets": extra_tel.get("weights_net", coin_targets_map) if is_v2_engine else coin_targets_map,
            "coin_books": sleeve_books_map if is_v2_engine else {},
            "coin_factors": extra_tel.get("factor_scores", {}) if is_v2_engine else {},
            "shadow_arena": arena_board,
        }
        self._state.save_snapshot()

        radar_list = self._state.get_coins_radar_list()
        self._db.upsert_coin_states(radar_list)

        if is_new_candle or force_recalc:
            btc_c = self._state.coins.get("BTCUSDT")
            use_vcap = bool(settings.USE_DEMO_TRADING and settings.VIRTUAL_EQUITY_CAP > 0.0)
            snap_bal = float(total_equity) if use_vcap else float(usdt_balance)
            snap_upnl = 0.0 if use_vcap else float(total_upnl)
            self._db.record_snapshot(
                balance_usdt=snap_bal,
                btc_pos_qty=btc_c.current_pos_qty if btc_c else 0.0,
                btc_price=coin_prices.get("BTCUSDT", 0.0),
                unrealized_pnl=snap_upnl,
                master_action=portfolio_dto.net_leverage,
                gross_leverage=portfolio_dto.total_gross_leverage,
                active_coins=active_coins_cnt,
            )

        rss_mb = memory_guard.trim_ram()
        self._logger.info(
            f"⚡ [{candle_ts} | {calc_ms:.0f}ms | RAM:{rss_mb:.1f}MB] Eq: ${total_equity:,.2f} | "
            f"Gross: {portfolio_dto.total_gross_leverage:.2f}x | Лідер: {self._state.latest_telemetry['top_leader']} | "
            f"Breadth: {portfolio_dto.market_breadth:+.2f}"
        )

        if executed_orders_summary:
            eng_title = "QuantCore V2 Multi-Sleeve (1h)" if is_v2_engine else "QuantCore V58.0 Pure SOTA"
            alert_txt = (
                f"⚡ <b>{eng_title}: Ребаланс виконано!</b>\n"
                f"═══════════════════════\n"
                + "\n".join(executed_orders_summary)
                + f"\n───────────────────────\n"
                f"• <b>Сумарний Equity:</b> <b>${total_equity:,.2f} USDT</b>\n"
                f"• <b>Експозиція Портфеля:</b> <code>{portfolio_dto.total_gross_leverage:.2f}x</code> (Net: <code>{portfolio_dto.net_leverage:+.2f}x</code>)\n"
                f"• <b>Топ-Лідер:</b> <code>{self._state.latest_telemetry['top_leader']}</code>"
            )
            await self._send_alert(alert_txt)