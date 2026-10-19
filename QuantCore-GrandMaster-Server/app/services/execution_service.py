import time
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
    Верховний Оркестратор Виконання (V23 Grand-Master & Universal Cartridge Runner):
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
        "_tg_sender",
        "_last_backup_date",
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
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._db = db_service
        self._exchange = exchange_service
        self._cartridges = cartridge_service
        self._learner = online_learner
        self._news = news_service
        self._tg_sender = None
        self._last_backup_date = datetime.now(timezone.utc).date()

    @property
    def name(self) -> str:
        return "MultiAssetExecutionOrchestrator"

    def bind_telegram_sender(self, tg_service) -> None:
        self._tg_sender = tg_service

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
                self._state.set_pause_state(paused=True, hours=24.0)
                await self.emergency_close_all_positions()
                msg = (
                    f"🛑 <b>CIRCUIT BREAKER АКТИВОВАНО!</b>\n\n"
                    f"• Просадка доби: <b>{dd:.2%}</b> (ліміт: {settings.MAX_DAILY_LOSS_PCT:.0%})\n"
                    f"• Усі позиції закрито в USDT, торгівлю призупинено на 24 години."
                )
                await self._send_alert(msg)
                return True
        return False

    async def _monitor_coin_breakeven(self, sym: str, current_price: float, atr_val: float) -> None:
        c = self._state.coins.get(sym)
        if not c or abs(c.current_pos_qty) <= 0.0 or c.entry_price <= 0.0 or c.is_breakeven or atr_val <= 0.0:
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
            await self._send_alert("▶️ <b>Час паузи вичерпано!</b> QuantCore V23 відновив штатну торгівлю.")

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

        # 1. Завантаження свічок по всіх підтримуваних валютах
        candles_map: Dict[str, pd.DataFrame] = {}
        for sym in active_syms:
            df = await self._exchange.fetch_delta_candles(sym, limit=settings.CANDLES_FETCH_LIMIT)
            if df is not None and len(df) >= 1650:
                candles_map[sym] = df

        if "BTCUSDT" not in candles_map:
            self._logger.warning("⚠️ Недостатньо свічок для BTCUSDT. Очікування наступної ітерації.")
            return

        candle_ts = str(candles_map["BTCUSDT"]["timestamp"].iloc[-1])
        is_new_candle = (candle_ts != self._state.last_candle_ts)
        if not force_recalc and not is_new_candle:
            return

        # 2. Синхронізація фактичного балансу та позицій з біржею Binance Futures
        usdt_balance, total_upnl, ex_positions, is_sync_ok = await self._exchange.fetch_account_snapshot(active_syms)
        if not is_sync_ok or usdt_balance <= 0.0:
            self._logger.warning("⚠️ Тимчасовий збій синхронізації балансу. Пропуск ребалансу без скидання ордерів.")
            return

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

        # 3. Оцінка новинного фону Gemini AI
        news_score = await self._news.get_sentiment_score()

        # 4. Запуск ШІ-картриджа для розрахунку цільового портфеля
        online_states = self._learner.get_all_learning_states()
        portfolio_dto = await asyncio.to_thread(
            cartridge.compute_portfolio_targets,
            candles_map,
            self._state.coins,
            online_states,
            self._state.max_portfolio_lev,
            self._state.orchestrator_mode,
            news_score,
        )

        # 5. Онлайн-самонавчання + перевірка Breakeven + Виконання ордерів
        executed_orders_summary: List[str] = []
        coin_targets_map: Dict[str, float] = {}

        for sym, target_dto in portfolio_dto.targets.items():
            c_st = self._state.coins.get(sym)
            if c_st is None:
                continue

            cur_p = target_dto.current_price
            cur_atr = target_dto.atr_14
            coin_targets_map[sym] = target_dto.desired_weight

            if is_new_candle:
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

            await self._monitor_coin_breakeven(sym, cur_p, cur_atr)

            min_qty, _, min_notional, _, _ = settings.get_symbol_spec(sym)
            cur_weight = (c_st.current_pos_qty * cur_p) / total_equity if total_equity > 0 else 0.0
            desired_w = target_dto.desired_weight if (c_st.enabled and c_st.mode != 0) else 0.0

            is_closing_to_cash = abs(desired_w) < settings.CASH_ZONE_THRESHOLD
            is_opening_from_cash = abs(cur_weight) < settings.CASH_ZONE_THRESHOLD and abs(desired_w) >= settings.CASH_ZONE_THRESHOLD
            is_flip = (cur_weight * desired_w) < 0.0
            weight_diff = abs(desired_w - cur_weight)

            if not (is_closing_to_cash or is_opening_from_cash or is_flip) and weight_diff < settings.ACTION_DEADZONE:
                continue

            if is_closing_to_cash:
                if abs(c_st.current_pos_qty) < min_qty:
                    continue
                delta_qty = -c_st.current_pos_qty
                reduce_only = True
                pnl_est = coin_upnl.get(sym, 0.0)
                note_str = f"Exit to Cash (F0 | Score:{target_dto.alpha_score:+.2f})"
            else:
                target_usdt = total_equity * desired_w
                target_qty_raw = target_usdt / max(1e-8, cur_p)
                target_qty = self._exchange.safe_amount(sym, abs(target_qty_raw))
                if desired_w < 0:
                    target_qty = -target_qty
                delta_qty = target_qty - c_st.current_pos_qty
                if abs(delta_qty) < min_qty or (abs(delta_qty) * cur_p) < min_notional:
                    continue
                is_partial_trim = (c_st.current_pos_qty * delta_qty) < 0.0 and not is_flip
                reduce_only = is_partial_trim
                if is_partial_trim and abs(c_st.current_pos_qty) > 0:
                    trim_ratio = min(1.0, abs(delta_qty) / abs(c_st.current_pos_qty))
                    pnl_est = coin_upnl.get(sym, 0.0) * trim_ratio
                else:
                    pnl_est = 0.0
                note_str = f"V23 Phase {target_dto.phase} ({desired_w:+.2f}x | MWU:{c_st.mwu_trust:.2f}x)"

            ord_dto = await self._exchange.execute_smart_rebalance_order(
                symbol=sym,
                delta_qty=delta_qty,
                mark_price=cur_p,
                realized_pnl_est=pnl_est,
                note=note_str,
                reduce_only=reduce_only,
            )

            if ord_dto is not None:
                old_qty = c_st.current_pos_qty
                signed_exec = ord_dto.executed_qty if ord_dto.side == "BUY" else -ord_dto.executed_qty
                new_pos_qty = 0.0 if is_closing_to_cash else (old_qty + signed_exec)

                if abs(new_pos_qty) >= min_qty:
                    if is_opening_from_cash or is_flip:
                        c_st.entry_price = ord_dto.avg_price
                        c_st.bars_held = 1
                        c_st.is_breakeven = False
                    elif (old_qty * signed_exec) > 0.0 and c_st.entry_price > 0.0:
                        # Додавання до існуючої позиції: середньозважена ціна входу
                        c_st.entry_price = (
                            (abs(old_qty) * c_st.entry_price) + (ord_dto.executed_qty * ord_dto.avg_price)
                        ) / max(1e-8, abs(new_pos_qty))

                    c_st.current_pos_qty = new_pos_qty

                    # Якщо вже був активований Breakeven — зберігаємо беззбитковий стоп!
                    if c_st.is_breakeven and c_st.entry_price > 0.0:
                        raw_sl = (
                            c_st.entry_price * (1.0 + settings.BREAKEVEN_BUFFER_PCT)
                            if new_pos_qty > 0
                            else c_st.entry_price * (1.0 - settings.BREAKEVEN_BUFFER_PCT)
                        )
                    else:
                        sl_dist = settings.EMERGENCY_SL_ATR_MULT * cur_atr
                        raw_sl = (c_st.entry_price - sl_dist) if new_pos_qty > 0 else (c_st.entry_price + sl_dist)

                    sl_p = self._exchange.safe_price(sym, raw_sl)
                    c_st.active_sl_price = sl_p
                    await self._exchange.place_or_update_stop_loss(sym, new_pos_qty, sl_p)

                    icon = "🟢" if ord_dto.side == "BUY" else "🔴"
                    executed_orders_summary.append(
                        f"{icon} <b>{sym}</b>: {ord_dto.side} <code>{ord_dto.executed_qty}</code> @ <code>${ord_dto.avg_price:,.2f}</code> "
                        f"➔ <b>{desired_w:+.2f}x</b> (SL: <code>${sl_p:,.2f}</code>)"
                    )
                else:
                    c_st.current_pos_qty = 0.0
                    c_st.entry_price = 0.0
                    c_st.active_sl_price = 0.0
                    c_st.is_breakeven = False
                    c_st.bars_held = 0
                    executed_orders_summary.append(
                        f"⚪ <b>{sym}</b>: Вихід у КЕШ @ <code>${ord_dto.avg_price:,.2f}</code> (PnL: <b>{pnl_est:+.2f}$</b>)"
                    )

        # 6. Збереження телеметрії, стану та SQLite зрізу
        self._learner.save_state()
        calc_ms = round((time.time() - t0) * 1000.0, 1)
        active_coins_cnt = sum(1 for c in self._state.coins.values() if abs(c.current_pos_qty) > 0)

        self._state.last_candle_ts = candle_ts
        self._state.latest_telemetry = {
            "timestamp": candle_ts,
            "calc_ms": calc_ms,
            "wallet_balance": round(usdt_balance, 2),
            "unrealized_pnl": round(total_upnl, 2),
            "total_equity": round(total_equity, 2),
            "gross_leverage": portfolio_dto.total_gross_leverage,
            "net_leverage": portfolio_dto.net_leverage,
            "market_breadth": portfolio_dto.market_breadth,
            "news_sentiment": portfolio_dto.news_sentiment,
            "active_coins_count": active_coins_cnt,
            "top_leader": portfolio_dto.extra_telemetry.get("top_leader", "BTCUSDT"),
            "coin_prices": coin_prices,
            "coin_upnl": coin_upnl,
            "coin_targets": coin_targets_map,
        }
        self._state.save_snapshot()

        radar_list = self._state.get_coins_radar_list()
        self._db.upsert_coin_states(radar_list)

        if is_new_candle:
            btc_c = self._state.coins.get("BTCUSDT")
            self._db.record_snapshot(
                balance_usdt=usdt_balance,
                btc_pos_qty=btc_c.current_pos_qty if btc_c else 0.0,
                btc_price=coin_prices.get("BTCUSDT", 0.0),
                unrealized_pnl=total_upnl,
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
            alert_txt = (
                f"⚡ <b>QuantCore V23 Grand-Master: Ребаланс виконано!</b>\n"
                f"═══════════════════════\n"
                + "\n".join(executed_orders_summary)
                + f"\n───────────────────────\n"
                f"• <b>Сумарний Equity:</b> <b>${total_equity:,.2f} USDT</b>\n"
                f"• <b>Експозиція Портфеля:</b> <code>{portfolio_dto.total_gross_leverage:.2f}x</code> [{self._state.risk_profile}]\n"
                f"• <b>Топ-Лідер:</b> <code>{self._state.latest_telemetry['top_leader']}</code>"
            )
            await self._send_alert(alert_txt)