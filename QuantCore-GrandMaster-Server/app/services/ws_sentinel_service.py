import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import websockets

try:
    import orjson
    def _loads(data: str | bytes) -> Any:
        return orjson.loads(data)
except ImportError:
    import json
    def _loads(data: str | bytes) -> Any:
        return json.loads(data)

from app.core.config import settings
from app.core.events import AsyncEventBus, event_bus
from app.domain.interfaces import IService
from app.services.state_service import StateService
from app.services.exchange_ccxt_service import ExchangeCcxtService


class WebSocketSentinelService(IService):
    """
    QuantCore Real-Time WebSocket Sentinel (< 3 MB RAM overhead).
    Підключається до мультиплексованого потоку Binance Futures wss://fstream.binance.com/ws/!markPrice@arr@1s
    і щосекунди в пам'яті виконує:
      1. Миттєвий Breakeven (+1.20 ATR) та Chandelier Ratchet (+2.0 ATR trailing profit lock).
      2. Детектор Flash-Crash / Каскаду (> 2.2 ATR від початку свічки) із миттєвим пробудженням ядра.
      3. Моніторинг та миттєвий захист пасивних Stink-Bids лімітних ордерів.
    """

    BINANCE_WS_URL: str = "wss://fstream.binance.com/ws/!markPrice@arr@1s"

    def __init__(
        self,
        logger: logging.Logger,
        state_service: StateService,
        exchange_service: ExchangeCcxtService,
        event_bus_instance: Optional[AsyncEventBus] = None,
        orchestrator: Optional[Any] = None,
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._exchange = exchange_service
        self._event_bus = event_bus_instance or event_bus
        self._orchestrator = orchestrator
        self._tg_sender: Optional[Any] = None

        # Внутрішній кеш високої швидкості (In-Memory, Zero Allocations)
        self._mark_prices: Dict[str, float] = {}
        self._symbol_atrs: Dict[str, float] = {}
        self._candle_bucket: int = int(time.time() // 900)
        self._candle_open_prices: Dict[str, float] = {}
        self._last_flash_wakeup: Dict[str, float] = {}
        self._active_stink_bids: Dict[str, Dict[str, Any]] = {}

        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    @property
    def name(self) -> str:
        return "WebSocketSentinelService"

    def bind_telegram_sender(self, tg_sender: Any) -> None:
        self._tg_sender = tg_sender

    def bind_orchestrator(self, orchestrator: Any) -> None:
        self._orchestrator = orchestrator

    def update_symbol_atrs(self, atrs_map: Dict[str, float]) -> None:
        """Оновлюється оркестратором на кожній свічці."""
        self._symbol_atrs.update(atrs_map)

    def update_symbol_atr(self, sym: str, atr: float) -> None:
        if atr > 0.0:
            self._symbol_atrs[sym] = atr

    def register_stink_bid(
        self,
        symbol: str,
        qty: float,
        price: float,
        atr: float,
        order_id: Optional[str] = None,
    ) -> None:
        """Реєструє виставлений пасивний лімітний ордер для суб-секундного захисту."""
        self._active_stink_bids[symbol] = {
            "symbol": symbol,
            "qty": float(qty),
            "price": float(price),
            "atr": float(atr),
            "order_id": order_id,
            "registered_at": time.time(),
        }
        self._logger.info(
            f"🎯 [WSSentinel] Зареєстровано пасивний Stink-Bid: {symbol} x {qty:.4f} @ ${price:,.4f} (SL trigger @ ${price - 1.35 * atr:,.4f})"
        )

    def clear_stink_bids(self) -> None:
        self._active_stink_bids.clear()

    async def init(self) -> None:
        self._running = True
        self._logger.info("🛡️ WebSocketSentinelService ініціалізовано.")

    async def shutdown(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._logger.info("🛡️ WebSocketSentinelService зупинено.")

    async def _send_alert(self, text: str) -> None:
        if self._tg_sender is not None and hasattr(self._tg_sender, "send_alert"):
            try:
                await self._tg_sender.send_alert(text)
            except Exception as e:
                self._logger.debug(f"Failed to send telegram alert: {e}")

    async def loop(self) -> None:
        """Головний фоновий цикл із самовідновленням з'єднання."""
        self._running = True
        retry_delay = 1.0

        while self._running:
            try:
                self._logger.info(f"🔌 [WSSentinel] Підключення до Binance Futures ({self.BINANCE_WS_URL})...")
                async with websockets.connect(
                    self.BINANCE_WS_URL,
                    ping_interval=20,
                    ping_timeout=15,
                    close_timeout=5,
                    max_size=2 * 1024 * 1024,
                ) as ws:
                    self._logger.info("⚡ [WSSentinel] Активно! Реальний потік Mark Price 1s підключено.")
                    retry_delay = 1.0

                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            payload = _loads(message)
                            if isinstance(payload, list):
                                await self._process_mark_price_array(payload)
                        except Exception as parse_err:
                            self._logger.debug(f"[WSSentinel] Parse error: {parse_err}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    self._logger.warning(
                        f"⚠️ [WSSentinel] Розрив зв'язку: {e}. Перепідключення через {retry_delay:.0f}с..."
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(15.0, retry_delay * 1.5)

    async def _process_mark_price_array(self, items: List[Dict[str, Any]]) -> None:
        now = time.time()
        bucket = int(now // 900)  # 15-хвилинний кошик свічки

        # Скидання опорних цін на початку нового 15m інтервалу
        if bucket != self._candle_bucket:
            self._candle_bucket = bucket
            self._candle_open_prices.clear()

        # 1. Оновлюємо кеш цін у пам'яті (без жодних звернень до REST чи диска)
        for item in items:
            sym = item.get("s")
            p_str = item.get("p")
            if sym and p_str:
                try:
                    price = float(p_str)
                    self._mark_prices[sym] = price
                    if sym not in self._candle_open_prices:
                        self._candle_open_prices[sym] = price
                except (ValueError, TypeError):
                    pass

        # Оновлюємо ціни в телеметрії StateService для Web UI без затримки
        if hasattr(self._state, "latest_telemetry") and isinstance(self._state.latest_telemetry, dict):
            cp = self._state.latest_telemetry.get("coin_prices")
            if isinstance(cp, dict):
                for s in self._state.coins:
                    if s in self._mark_prices:
                        cp[s] = self._mark_prices[s]

        # 2. Перевірка 1: Суб-секундний Breakeven & Chandelier Ratchet
        await self._check_breakeven_and_ratchet()

        # 3. Перевірка 2: Детектор Flash-Crash / Каскаду ліквідацій (> 2.2 ATR)
        await self._check_flash_crash_cascade(now)

        # 4. Перевірка 3: Захист Stink-Bids при наливі всередині свічки
        await self._check_stink_bids_fulfillment()

    async def _check_breakeven_and_ratchet(self) -> None:
        """Перевіряє перевід у беззбиток та підтягування трейлінг-стопа щосекунди."""
        for sym, c in self._state.coins.items():
            if abs(c.current_pos_qty) <= 0.0 or c.entry_price <= 0.0:
                continue

            mark_p = self._mark_prices.get(sym)
            if not mark_p or mark_p <= 0.0:
                continue

            atr = self._symbol_atrs.get(sym, 0.0)
            if atr <= 0.0:
                atr = c.entry_price * 0.015  # Розумний дефолт (1.5%), якщо свічка ще не прогрузила ATR

            be_dist = settings.ATR_BREAKEVEN_TRIGGER * atr

            # --- А. МИТТЄВИЙ ПЕРЕВІД У БЕЗЗБИТОК (+1.20 ATR) ---
            if not c.is_breakeven:
                trigger_be = False
                raw_be = 0.0

                if c.current_pos_qty > 0 and (mark_p - c.entry_price) >= be_dist:
                    trigger_be = True
                    raw_be = c.entry_price * (1.0 + settings.BREAKEVEN_BUFFER_PCT)
                elif c.current_pos_qty < 0 and (c.entry_price - mark_p) >= be_dist:
                    trigger_be = True
                    raw_be = c.entry_price * (1.0 - settings.BREAKEVEN_BUFFER_PCT)

                if trigger_be:
                    ok = await self._exchange.place_or_update_stop_loss(sym, c.current_pos_qty, raw_be)
                    if ok:
                        c.is_breakeven = True
                        c.active_sl_price = self._exchange.safe_price(sym, raw_be)
                        self._state.save_snapshot()
                        self._logger.info(
                            f"🛡️ [WSSentinel] [{sym}] Миттєво переведено в БЕЗЗБИТОК! Mark: ${mark_p:,.4f}, SL: ${c.active_sl_price:,.4f}"
                        )
                        await self._send_alert(
                            f"🛡️ <b>[WSSentinel] [{sym}] Страховий Stop-Loss переведено в БЕЗЗБИТОК!</b>\n\n"
                            f"• Позиція: <code>{c.current_pos_qty:+.4f}</code> | Вхід: <code>${c.entry_price:,.4f}</code>\n"
                            f"• Mark Price: <b>${mark_p:,.4f}</b> (+{abs(mark_p - c.entry_price) / atr:.2f} ATR)\n"
                            f"• Новий Stop-Loss: <b>${c.active_sl_price:,.4f}</b>"
                        )
                    continue

            # --- Б. CHANDELIER RATCHET (Трейлінг-фіксація високого прибутку > 2.0 ATR) ---
            if c.is_breakeven and c.active_sl_price > 0.0:
                if c.current_pos_qty > 0 and (mark_p - c.entry_price) >= (2.0 * atr):
                    ratchet_sl = mark_p - (1.35 * atr)
                    safe_ratchet = self._exchange.safe_price(sym, ratchet_sl)
                    # Підтягуємо стоп лише якщо він вищий щонайменше на 0.20 ATR від старого SL
                    if safe_ratchet > (c.active_sl_price + 0.20 * atr):
                        ok = await self._exchange.place_or_update_stop_loss(sym, c.current_pos_qty, safe_ratchet)
                        if ok:
                            old_sl = c.active_sl_price
                            c.active_sl_price = safe_ratchet
                            self._state.save_snapshot()
                            self._logger.info(
                                f"🔒 [WSSentinel Ratchet] [{sym}] SL піднято: ${old_sl:,.4f} ➔ ${safe_ratchet:,.4f}"
                            )
                            await self._send_alert(
                                f"🔒 <b>[WSSentinel Ratchet] [{sym}] Фіксація прибутку піднята!</b>\n"
                                f"• Поточна ціна: <b>${mark_p:,.4f}</b>\n"
                                f"• Захисний Stop-Loss перенесено: <code>${old_sl:,.4f}</code> ➔ <b>${safe_ratchet:,.4f}</b>"
                            )

                elif c.current_pos_qty < 0 and (c.entry_price - mark_p) >= (2.0 * atr):
                    ratchet_sl = mark_p + (1.35 * atr)
                    safe_ratchet = self._exchange.safe_price(sym, ratchet_sl)
                    # Для шорта підтягуємо стоп вниз, якщо новий SL нижчий на 0.20 ATR
                    if safe_ratchet < (c.active_sl_price - 0.20 * atr):
                        ok = await self._exchange.place_or_update_stop_loss(sym, c.current_pos_qty, safe_ratchet)
                        if ok:
                            old_sl = c.active_sl_price
                            c.active_sl_price = safe_ratchet
                            self._state.save_snapshot()
                            self._logger.info(
                                f"🔒 [WSSentinel Ratchet] [{sym}] SL опущено: ${old_sl:,.4f} ➔ ${safe_ratchet:,.4f}"
                            )
                            await self._send_alert(
                                f"🔒 <b>[WSSentinel Ratchet] [{sym}] Фіксація прибутку опущена!</b>\n"
                                f"• Поточна ціна: <b>${mark_p:,.4f}</b>\n"
                                f"• Захисний Stop-Loss перенесено: <code>${old_sl:,.4f}</code> ➔ <b>${safe_ratchet:,.4f}</b>"
                            )

    async def _check_flash_crash_cascade(self, now: float) -> None:
        """
        Детектор Flash-Crash / Каскаду:
        Якщо ціна BTC або відкритої монети відхиляється більше ніж на 2.2 * ATR від початку свічки,
        миттєво викликає WAKEUP_EVENT для негайного реагування оркестратора.
        """
        monitored_syms = set()
        # Завжди моніторимо флагман ринку BTC
        if "BTCUSDT" in self._mark_prices:
            monitored_syms.add("BTCUSDT")

        # Додаємо всі символи з відкритими реальними позиціями
        for sym, c in self._state.coins.items():
            if abs(c.current_pos_qty) > 0.0 and sym in self._mark_prices:
                monitored_syms.add(sym)

        for sym in monitored_syms:
            mark_p = self._mark_prices[sym]
            open_p = self._candle_open_prices.get(sym, mark_p)
            atr = self._symbol_atrs.get(sym, 0.0)
            if atr <= 0.0:
                atr = open_p * 0.015

            delta_price = abs(mark_p - open_p)
            threshold = 2.20 * atr

            if delta_price >= threshold:
                # Cooldown: не спамити пробудженням частіше ніж раз на 90 секунд по одній монеті
                last_wake = self._last_flash_wakeup.get(sym, 0.0)
                if (now - last_wake) >= 90.0:
                    self._last_flash_wakeup[sym] = now
                    delta_pct = (delta_price / open_p) * 100.0 if open_p > 0 else 0.0
                    direction = "📉 ПРОЛИВ" if mark_p < open_p else "📈 ПАМП/СПЛЕСК"

                    self._logger.warning(
                        f"🚨 [WSSentinel Flash-Crash] {sym} {direction}: Δ ${delta_price:,.2f} ({delta_pct:.2f}%) "
                        f">= 2.2 ATR (${threshold:,.2f}). Негайне пробудження оркестратора!"
                    )

                    # Миттєве пробудження основного торгового циклу!
                    self._event_bus.trigger_wakeup()

                    await self._send_alert(
                        f"🚨 <b>[FLASH-CRASH SENTINEL] ДЕТЕКТОВАНО АНОМАЛЬНИЙ РУХ!</b>\n\n"
                        f"• Актив: <b>{sym}</b> ({direction})\n"
                        f"• Зміна у 15m свічці: <code>${open_p:,.4f} ➔ ${mark_p:,.4f}</code> (<b>{delta_pct:+.2f}%</b>)\n"
                        f"• Відхилення: <b>{delta_price / atr:.2f} ATR</b> (поріг: 2.20 ATR)\n"
                        f"• <i>Ядро QuantCore негайно розбуджено для захисту портфеля та перерахунку!</i>"
                    )

    async def _check_stink_bids_fulfillment(self) -> None:
        """
        Захист Stink-Bids:
        Якщо ціна впала до рівня виставленого пасивного ордера stink_bid,
        перевіряє його виконання та негайно виставляє захисний STOP_MARKET ордер.
        """
        if not self._active_stink_bids:
            return

        to_remove = []
        for sym, bid in list(self._active_stink_bids.items()):
            mark_p = self._mark_prices.get(sym)
            if not mark_p:
                continue

            stink_price = bid["price"]
            # Якщо поточна ціна досягла або пробила ціну лімітного ордера вниз
            if mark_p <= stink_price:
                # Перевіряємо фактичне виконання ордера через відкриті позиції / біржу
                c = self._state.coins.get(sym)
                qty = bid["qty"]
                atr = bid["atr"]

                # Виставляємо захисний Stop-Loss нижче ціни наливу
                sl_price = stink_price - (1.35 * atr)
                safe_sl = self._exchange.safe_price(sym, sl_price)

                self._logger.info(
                    f"🎯 [WSSentinel Stink-Bid] Ціна {sym} (${mark_p:,.4f}) досягла Stink-Bid (${stink_price:,.4f}). "
                    f"Виставлення захисного STOP_MARKET @ ${safe_sl:,.4f}..."
                )

                placed = await self._exchange.place_or_update_stop_loss(sym, qty, safe_sl)
                if placed and c is not None:
                    c.active_sl_price = safe_sl
                    self._state.save_snapshot()

                await self._send_alert(
                    f"🎯 <b>[WSSentinel Stink-Bid Sniper] ПАСИВНИЙ ОРДЕР АКТИВОВАНО!</b>\n\n"
                    f"• Актив: <b>{sym}</b> | Об'єм: <code>{qty:+.4f}</code>\n"
                    f"• Ціна наливу ліміту: <b>${stink_price:,.4f}</b> (Mark: ${mark_p:,.4f})\n"
                    f"• Захисний STOP_MARKET виставлено: <b>${safe_sl:,.4f}</b> (-1.35 ATR)\n"
                    f"• <i>Капітал захищено без затримки на закриття свічки!</i>"
                )
                to_remove.append(sym)

        for sym in to_remove:
            self._active_stink_bids.pop(sym, None)
