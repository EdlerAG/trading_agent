# -*- coding: utf-8 -*-
"""Модульний асинхронний виконавець V6.2-B `Smart Maker` (Post-Only `GTX` Chase + Implementation Shortfall).

Ключові інваріанти безпеки та виконання:
  1. Самодостатній модуль із суворою типізацією (`Protocol` адаптер біржі, ін'єкція `clock_fn`/`sleep_fn` для 0ms тестів).
  2. Легкий L1 BBO (`bookTicker` / локальний WS-кеш) без важких `fetch_order_book` запитів.
  3. Перестановка котировки лише при зсуві L1 >= `max(tick_size, arrival_mid * reprice_bps / 10_000)` (захист від мілі-тіків BTC/ETH).
  4. Миттєвий перехід у `MARKET` при перевищенні `max_drift_bps` (Adverse Drift Cap).
  5. Асиметричне правило `minNotional` (захист від `-4164` на входах та повне дозакриття міні-залишків на `reduceOnly=True`).
  6. Захист від race condition `-2011` (`OrderNotFound`) на `cancel_order` із обов'язковим фінальним `fetch_order` (0 подвійних філів).
  7. Інтелектуальне відновлення `-2022` на `GTX reduceOnly`: зняття конфліктного `STOP_MARKET`, затискання обсягу до `abs(live_qty)`,
     продовження пасивного chase та гарантоване перевиставлення `STOP_MARKET` у `finally`.
  8. Куленепробивний `finally` (включно з `asyncio.CancelledError`): скасування активної лімітки, зняття лока `active_chase_symbols`
     та відновлення `STOP_MARKET` для відкритої позиції.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, Set, Tuple

from app.core.config import ccxt_to_symbol, settings
from app.domain.schemas import OrderExecutionDTO


@dataclass(frozen=True, slots=True)
class SmartMakerConfig:
    """Конфігурація алгоритму `Smart Maker` Post-Only Chase."""

    enabled: bool = False
    max_attempts: int = 3
    poll_sec: float = 12.0
    poll_interval_sec: float = 2.0
    reprice_bps: float = 3.0
    max_drift_bps: float = 25.0
    min_notional_usd: float = 15.0
    concurrency: int = 4
    post_only_backoff_sec: float = 0.35
    max_order_budget_sec: float = 40.0
    vip0_maker_fee_bps: float = 2.0
    vip0_taker_fee_bps: float = 5.0

    @classmethod
    def from_settings(cls, cfg_obj: Any = settings) -> SmartMakerConfig:
        enabled = bool(
            getattr(cfg_obj, "SMART_MAKER_CHASE_ENABLED", False)
            or getattr(cfg_obj, "ENABLE_SMART_MAKER_CHASE", False)
        )
        max_att = max(1, int(getattr(cfg_obj, "SMART_MAKER_MAX_ATTEMPTS", 3)))
        poll_s = max(0.2, float(getattr(cfg_obj, "SMART_MAKER_POLL_SEC", 12.0)))
        poll_int = min(2.0, max(0.2, poll_s / 6.0))
        return cls(
            enabled=enabled,
            max_attempts=max_att,
            poll_sec=poll_s,
            poll_interval_sec=poll_int,
            reprice_bps=max(0.1, float(getattr(cfg_obj, "SMART_MAKER_REPRICE_BPS", 3.0))),
            max_drift_bps=max(1.0, float(getattr(cfg_obj, "SMART_MAKER_MAX_DRIFT_BPS", 25.0))),
            min_notional_usd=max(0.0, float(getattr(cfg_obj, "SMART_MAKER_MIN_NOTIONAL_USD", 15.0))),
            concurrency=max(1, int(getattr(cfg_obj, "SMART_MAKER_CONCURRENCY", 4))),
            max_order_budget_sec=40.0,
        )


@dataclass(slots=True)
class BBOQuote:
    """Легкий знімок L1 стакана (`best_bid`, `best_ask`)."""

    bid: float
    ask: float
    timestamp: float = 0.0

    @property
    def mid(self) -> float:
        if self.bid > 0.0 and self.ask > 0.0:
            return 0.5 * (self.bid + self.ask)
        return max(self.bid, self.ask, 0.0)

    @property
    def spread_bps(self) -> float:
        m = self.mid
        if m <= 0.0 or self.ask < self.bid:
            return 0.0
        return (self.ask - self.bid) / m * 10_000.0


@dataclass(slots=True)
class SmartMakerTelemetry:
    """Повна телеметрія якості виконання (`Implementation Shortfall` + статистика chase)."""

    exec_mode: str = "market_direct"  # "smart_maker" | "market_fallback" | "market_direct"
    arrival_bid: float = 0.0
    arrival_ask: float = 0.0
    arrival_mid: float = 0.0
    bbo_spread_bps: float = 0.0
    avg_fill_price: float = 0.0
    maker_filled_qty: float = 0.0
    taker_filled_qty: float = 0.0
    maker_fill_ratio: float = 0.0
    chase_attempts: int = 0
    cancel_count: int = 0
    post_only_rejects_5022: int = 0
    drift_abort: bool = False
    fee_usdt: float = 0.0
    effective_fee_bps: float = 0.0
    implementation_shortfall_bps: float = 0.0
    limit_placed_price: float = 0.0
    latency_ms: float = 0.0
    order_status: str = "REJECTED"
    fallback_reason: str = ""
    sl_rearmed_after_2022: bool = False

    def to_diag_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["arrival_mid_px"] = self.arrival_mid
        d["spread_bps"] = self.bbo_spread_bps
        d["best_bid"] = self.arrival_bid
        d["best_ask"] = self.arrival_ask
        d["requotes_count"] = max(0, self.chase_attempts - 1)
        return d


@dataclass(slots=True)
class SmartMakerResult:
    """Об'єднаний результат виконання ордера та його мікроструктурної телеметрії."""

    dto: Optional[OrderExecutionDTO]
    telemetry: SmartMakerTelemetry


class ISmartMakerExchangeAdapter(Protocol):
    """Мінімальний асинхронний інтерфейс біржі для `SmartMakerExecutor`."""

    async def fetch_bbo_quote(self, symbol: str, fallback_price: float) -> BBOQuote: ...

    async def place_post_only_limit(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict[str, Any]: ...

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict[str, Any]: ...

    async def cancel_order_by_id(self, symbol: str, order_id: str) -> None: ...

    async def fetch_order_by_id(self, symbol: str, order_id: str) -> Optional[Dict[str, Any]]: ...

    async def fetch_live_position_qty(self, symbol: str) -> Optional[float]: ...

    async def cancel_symbol_orders_capture_sl(self, symbol: str) -> float: ...

    async def place_or_update_stop_loss_ex(
        self, symbol: str, position_qty: float, stop_price: float
    ) -> Tuple[bool, str]: ...

    def build_client_order_id(
        self, symbol: str, side: str, qty: float, reduce_only: bool, bucket_tag: str
    ) -> str: ...

    def get_symbol_filters(self, symbol: str) -> Tuple[float, float, float, float]:
        """Повертає `(min_qty, step_size, min_notional, tick_size)`."""
        ...


def step_floor_qty(qty: float, step_size: float) -> float:
    if qty <= 0.0:
        return 0.0
    if step_size <= 0.0:
        return float(qty)
    steps = math.floor((float(qty) / float(step_size)) + 1e-9)
    decimals = max(0, int(round(-math.log10(step_size)))) if step_size < 1.0 else 0
    return round(steps * float(step_size), max(decimals, 8))


def round_passive_price(raw_price: float, side: str, tick_size: float) -> float:
    """Округлює пасивну ціну строго на пасивній стороні спреду (floor для BUY, ceil для SELL)."""
    if raw_price <= 0.0 or tick_size <= 0.0:
        return float(raw_price)
    ratio = float(raw_price) / float(tick_size)
    if side.lower() == "buy":
        ticks = math.floor(ratio + 1e-9)
    else:
        ticks = math.ceil(ratio - 1e-9)
    decimals = max(0, int(round(-math.log10(tick_size)))) if tick_size < 1.0 else 0
    return round(max(1, ticks) * float(tick_size), max(decimals, 8))


def compute_effective_fee_and_is_bps(
    side: str,
    arrival_mid: float,
    avg_fill_price: float,
    maker_filled_qty: float,
    taker_filled_qty: float,
    explicit_fee_usdt: float = 0.0,
    has_complete_explicit_fee: bool = False,
    vip0_maker_bps: float = 2.0,
    vip0_taker_bps: float = 5.0,
) -> Tuple[float, float, float]:
    """Обчислює `(fee_usdt, effective_fee_bps, implementation_shortfall_bps)`.

    Конвенція знаку `implementation_shortfall_bps`:
      `side_sign * (avg_fill_price - arrival_mid) / arrival_mid * 10_000 + effective_fee_bps`
      - `> 0`: чиста витрата виконання відносно `arrival_mid` з урахуванням комісій;
      - `< 0`: покращення ціни пасивним мейкером перекрило комісію біржі.
    """
    tot_qty = float(maker_filled_qty) + float(taker_filled_qty)
    if tot_qty <= 0.0 or avg_fill_price <= 0.0 or arrival_mid <= 0.0:
        return 0.0, 0.0, 0.0

    notional = tot_qty * float(avg_fill_price)
    if has_complete_explicit_fee and explicit_fee_usdt >= 0.0:
        eff_fee_usd = float(explicit_fee_usdt)
        eff_fee_bps = (eff_fee_usd / max(notional, 1e-12)) * 10_000.0
    else:
        eff_fee_bps = (
            float(maker_filled_qty) * float(vip0_maker_bps)
            + float(taker_filled_qty) * float(vip0_taker_bps)
        ) / tot_qty
        eff_fee_usd = notional * (eff_fee_bps / 10_000.0)

    side_sign = 1.0 if side.upper() == "BUY" else -1.0
    raw_slip_bps = side_sign * (float(avg_fill_price) - float(arrival_mid)) / float(arrival_mid) * 10_000.0
    is_bps = raw_slip_bps + eff_fee_bps
    return round(eff_fee_usd, 6), round(eff_fee_bps, 4), round(is_bps, 4)


def _is_post_only_reject_5022(err: BaseException) -> bool:
    s = str(err)
    sl = s.lower()
    return (
        "-5022" in s
        or "post only" in sl
        or "postonly" in sl
        or "immediately match" in sl
        or "could not be executed as maker" in sl
    )


def _is_order_not_found_2011(err: BaseException) -> bool:
    s = str(err)
    sl = s.lower()
    return (
        "-2011" in s
        or "unknown order" in sl
        or "ordernotfound" in sl
        or "order does not exist" in sl
    )


def _is_reduce_only_reject_2022(err: BaseException) -> bool:
    s = str(err)
    return ("-2022" in s) or ("reduceonly" in s.lower())


def _extract_fill_tuple(
    ord_dict: Optional[Dict[str, Any]], fallback_px: float
) -> Tuple[float, float, Optional[float], str, str]:
    """Повертає `(filled_qty, avg_price, explicit_fee_or_None, status_lower, order_id)`."""
    if not isinstance(ord_dict, dict):
        return 0.0, 0.0, None, "", ""
    oid = str(ord_dict.get("id") or (ord_dict.get("info") or {}).get("orderId") or "")
    st = str(ord_dict.get("status") or (ord_dict.get("info") or {}).get("status") or "").strip().lower()
    raw_filled = ord_dict.get("filled")
    if raw_filled is None:
        raw_filled = (ord_dict.get("info") or {}).get("executedQty")
    f_qty = float(raw_filled or 0.0)
    if f_qty <= 0.0:
        return 0.0, 0.0, None, st, oid

    avg_px = float(
        ord_dict.get("average")
        or (ord_dict.get("info") or {}).get("avgPrice")
        or ord_dict.get("price")
        or fallback_px
        or 0.0
    )
    fee_obj = ord_dict.get("fee")
    explicit_fee: Optional[float] = None
    if isinstance(fee_obj, dict) and fee_obj.get("cost") is not None:
        explicit_fee = float(fee_obj["cost"])
    return f_qty, avg_px, explicit_fee, st, oid


class SmartMakerExecutor:
    """Асинхронний виконавець `Smart Maker` Post-Only Chase із захисним реєстром `active_chase_symbols`."""

    __slots__ = ("_adapter", "_logger", "_active_chase_symbols", "_seq_counter", "_clock_fn", "_sleep_fn")

    def __init__(
        self,
        adapter: ISmartMakerExchangeAdapter,
        logger: logging.Logger,
        active_chase_symbols: Optional[Set[str]] = None,
        clock_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._adapter = adapter
        self._logger = logger
        self._active_chase_symbols: Set[str] = active_chase_symbols if active_chase_symbols is not None else set()
        self._seq_counter: int = 0
        self._clock_fn = clock_fn
        self._sleep_fn = sleep_fn

    @property
    def active_chase_symbols(self) -> Set[str]:
        return self._active_chase_symbols

    def is_symbol_chasing(self, symbol: str) -> bool:
        return ccxt_to_symbol(symbol) in self._active_chase_symbols

    def _next_nonce(self) -> str:
        self._seq_counter = (self._seq_counter + 1) % 1_000_000
        ms_tail = int(time.time() * 1000) % 10_000_000
        return f"{ms_tail}_{self._seq_counter}"

    async def execute_smart_maker_order(
        self,
        symbol: str,
        delta_qty: float,
        mark_price: float,
        realized_pnl_est: float = 0.0,
        note: str = "",
        reduce_only: bool = False,
        active_sl_price: float = 0.0,
        force_market: bool = False,
        cfg: Optional[SmartMakerConfig] = None,
    ) -> SmartMakerResult:
        eff_cfg = cfg or SmartMakerConfig.from_settings(settings)
        t_start = self._clock_fn()
        clean_sym = ccxt_to_symbol(symbol)
        side = "buy" if delta_qty > 0 else "sell"
        side_up = side.upper()
        side_sign = 1.0 if side == "buy" else -1.0

        min_qty, step_size, ex_min_notional, tick_size = self._adapter.get_symbol_filters(clean_sym)
        target_qty = step_floor_qty(abs(float(delta_qty)), step_size)

        tel = SmartMakerTelemetry()
        if target_qty < min_qty:
            tel.arrival_mid = float(mark_price)
            tel.order_status = "REJECTED_MIN_QTY"
            return SmartMakerResult(dto=None, telemetry=tel)

        # Зафіксувати arrival BBO перед 1-ю спробою (легкий L1 bookTicker / WS BBO)
        arr_bbo = await self._adapter.fetch_bbo_quote(clean_sym, fallback_price=mark_price)
        arrival_bid = arr_bbo.bid if arr_bbo.bid > 0 else float(mark_price)
        arrival_ask = arr_bbo.ask if arr_bbo.ask > 0 else float(mark_price)
        arrival_mid = arr_bbo.mid if arr_bbo.mid > 0 else float(mark_price)
        tel.arrival_bid = float(arrival_bid)
        tel.arrival_ask = float(arrival_ask)
        tel.arrival_mid = float(arrival_mid)
        tel.bbo_spread_bps = round(float(arr_bbo.spread_bps), 3)

        # Перевірка максимального спреду для нових входів
        max_sp_bps = float(settings.MAX_ALLOWED_SPREAD_PCT) * 10_000.0
        if not reduce_only and tel.bbo_spread_bps > max_sp_bps:
            tel.order_status = "REJECTED_SPREAD"
            tel.fallback_reason = "spread_exceeded"
            tel.latency_ms = round(max(0.0, (self._clock_fn() - t_start) * 1000.0), 1)
            return SmartMakerResult(dto=None, telemetry=tel)

        est_px = arrival_ask if side == "buy" else arrival_bid
        if not reduce_only and (target_qty * est_px) < ex_min_notional:
            tel.order_status = "REJECTED_MIN_NOTIONAL"
            tel.fallback_reason = "below_exchange_min_notional"
            tel.latency_ms = round(max(0.0, (self._clock_fn() - t_start) * 1000.0), 1)
            return SmartMakerResult(dto=None, telemetry=tel)

        # Стан накопичення філів із захистом від подвійного обліку одного order_id
        recorded_oids: Set[str] = set()
        cum_maker_qty: float = 0.0
        cum_maker_cost: float = 0.0
        cum_taker_qty: float = 0.0
        cum_taker_cost: float = 0.0
        explicit_fee_sum: float = 0.0
        all_fills_had_explicit_fee: bool = True
        any_fill_seen: bool = False
        last_order_id: str = ""

        active_limit_order_id: Optional[str] = None
        active_limit_px: float = 0.0
        captured_sl_px: float = 0.0
        sl_stripped_during_chase: bool = False
        aborted_by_exception: bool = False

        def _record_maker_fill(oid: str, qty: float, avg_px: float, exp_fee: Optional[float]) -> None:
            nonlocal cum_maker_qty, cum_maker_cost, explicit_fee_sum, all_fills_had_explicit_fee, any_fill_seen, last_order_id
            if qty <= 0.0 or (oid and oid in recorded_oids):
                return
            if oid:
                recorded_oids.add(oid)
                last_order_id = oid
            px_use = avg_px if avg_px > 0.0 else (active_limit_px or arrival_mid)
            cum_maker_qty += float(qty)
            cum_maker_cost += float(qty) * float(px_use)
            any_fill_seen = True
            if exp_fee is not None:
                explicit_fee_sum += float(exp_fee)
            else:
                all_fills_had_explicit_fee = False

        def _record_taker_fill(oid: str, qty: float, avg_px: float, exp_fee: Optional[float]) -> None:
            nonlocal cum_taker_qty, cum_taker_cost, explicit_fee_sum, all_fills_had_explicit_fee, any_fill_seen, last_order_id
            if qty <= 0.0 or (oid and oid in recorded_oids):
                return
            if oid:
                recorded_oids.add(oid)
                last_order_id = oid
            px_use = avg_px if avg_px > 0.0 else (est_px or arrival_mid)
            cum_taker_qty += float(qty)
            cum_taker_cost += float(qty) * float(px_use)
            any_fill_seen = True
            if exp_fee is not None:
                explicit_fee_sum += float(exp_fee)
            else:
                all_fills_had_explicit_fee = False

        async def _cancel_and_harvest_limit(oid: str) -> None:
            """Безпечне скасування активної лімітки з перехопленням `-2011` та обов'язковим фінальним `fetch_order`."""
            nonlocal active_limit_order_id
            tel.cancel_count += 1
            try:
                await self._adapter.cancel_order_by_id(clean_sym, oid)
            except Exception as cancel_err:
                if not _is_order_not_found_2011(cancel_err):
                    self._logger.warning(f"⚠️ [{clean_sym}] cancel_order({oid}) помилка: {cancel_err}")
            try:
                final_ord = await self._adapter.fetch_order_by_id(clean_sym, oid)
                f_q, f_px, f_fee, _st, _ = _extract_fill_tuple(final_ord, active_limit_px or arrival_mid)
                if f_q > 0.0:
                    _record_maker_fill(oid, f_q, f_px, f_fee)
                elif oid:
                    recorded_oids.add(oid)
            except Exception as fetch_err:
                self._logger.warning(f"⚠️ [{clean_sym}] fetch_order({oid}) після cancel не вдався: {fetch_err}")
            finally:
                if active_limit_order_id == oid:
                    active_limit_order_id = None

        # Реєструємо символ в активному лоці chase
        self._active_chase_symbols.add(clean_sym)
        order_deadline = t_start + float(eff_cfg.max_order_budget_sec)
        reprice_threshold = max(float(tick_size), float(arrival_mid) * float(eff_cfg.reprice_bps) / 10_000.0)

        # Перевірка порогу номіналу для входу/добору (`SMART_MAKER_MIN_NOTIONAL_USD`) та периметру `force_market`
        use_passive_chase = bool(eff_cfg.enabled and not force_market)
        if use_passive_chase and (not reduce_only) and (target_qty * arrival_mid) < float(eff_cfg.min_notional_usd):
            use_passive_chase = False
            tel.fallback_reason = "below_smart_maker_min_notional"

        dust_clean_exit = False
        terminal_2022_status: Optional[str] = None

        try:
            if use_passive_chase:
                cur_bbo = arr_bbo
                for attempt in range(1, eff_cfg.max_attempts + 1):
                    if self._clock_fn() >= order_deadline:
                        tel.fallback_reason = tel.fallback_reason or "order_budget_exhausted"
                        break

                    if attempt > 1:
                        cur_bbo = await self._adapter.fetch_bbo_quote(clean_sym, fallback_price=arrival_mid)

                    cur_mid = cur_bbo.mid if cur_bbo.mid > 0 else arrival_mid
                    adverse_drift_bps = side_sign * (cur_mid - arrival_mid) / max(arrival_mid, 1e-12) * 10_000.0
                    if adverse_drift_bps > float(eff_cfg.max_drift_bps):
                        tel.drift_abort = True
                        tel.fallback_reason = "adverse_drift_cap"
                        break

                    rem_qty = step_floor_qty(max(0.0, target_qty - (cum_maker_qty + cum_taker_qty)), step_size)
                    if rem_qty < min_qty:
                        dust_clean_exit = True
                        break

                    ref_px = (cur_bbo.ask if side == "buy" else cur_bbo.bid) or cur_mid
                    if (rem_qty * ref_px) < ex_min_notional:
                        if not reduce_only:
                            # На вході залишок < minNotional -> чистий вихід без MARKET (захист від -4164)
                            dust_clean_exit = True
                            tel.fallback_reason = "residual_below_min_notional_entry"
                            break
                        else:
                            # На reduceOnly=True залишок >= min_qty, але < minNotional -> вихід із LIMIT циклу в MARKET reduceOnly!
                            tel.fallback_reason = "reduce_only_sub_notional_tail"
                            break

                    raw_passive = (cur_bbo.bid if side == "buy" else cur_bbo.ask) or cur_mid
                    limit_px = round_passive_price(raw_passive, side, tick_size)
                    if cur_bbo.bid > 0 and cur_bbo.ask > 0 and tick_size > 0:
                        if side == "buy" and limit_px >= cur_bbo.ask:
                            limit_px = round_passive_price(cur_bbo.ask - tick_size, "buy", tick_size)
                        elif side == "sell" and limit_px <= cur_bbo.bid:
                            limit_px = round_passive_price(cur_bbo.bid + tick_size, "sell", tick_size)

                    tel.chase_attempts += 1
                    tel.limit_placed_price = float(limit_px)
                    active_limit_px = float(limit_px)
                    cid = self._adapter.build_client_order_id(
                        clean_sym, side, rem_qty, reduce_only, bucket_tag=f"sm_{attempt}_{self._next_nonce()}"
                    )

                    placed_ord: Optional[Dict[str, Any]] = None
                    try:
                        placed_ord = await self._adapter.place_post_only_limit(
                            symbol=clean_sym,
                            side=side,
                            qty=rem_qty,
                            price=limit_px,
                            reduce_only=reduce_only,
                            client_order_id=cid,
                        )
                    except Exception as place_err:
                        if _is_post_only_reject_5022(place_err):
                            tel.post_only_rejects_5022 += 1
                            tel.fallback_reason = "post_only_5022"
                            await self._sleep_fn(eff_cfg.post_only_backoff_sec)
                            continue
                        if reduce_only and _is_reduce_only_reject_2022(place_err):
                            live_q = await self._adapter.fetch_live_position_qty(clean_sym)
                            if live_q is None:
                                terminal_2022_status = "FAILED_2022_RETRY"
                                break
                            if abs(live_q) < min_qty:
                                await self._adapter.cancel_symbol_orders_capture_sl(clean_sym)
                                terminal_2022_status = "ALREADY_CLOSED_2022"
                                break
                            exp_side = "sell" if live_q > 0 else "buy"
                            if side != exp_side:
                                terminal_2022_status = "FAILED_2022_SIDE_MISMATCH"
                                break
                            # Позиція відкрита, квоту блокує STOP_MARKET -> знімаємо SL, затискаємо qty і продовжуємо поточну спробу!
                            cap_sl = await self._adapter.cancel_symbol_orders_capture_sl(clean_sym)
                            if cap_sl > 0.0 and captured_sl_px <= 0.0:
                                captured_sl_px = cap_sl
                            sl_stripped_during_chase = True
                            clamped_rem = step_floor_qty(min(rem_qty, abs(live_q)), step_size)
                            target_qty = (cum_maker_qty + cum_taker_qty) + clamped_rem
                            if clamped_rem < min_qty:
                                terminal_2022_status = "ALREADY_CLOSED_2022"
                                break
                            if (clamped_rem * ref_px) < ex_min_notional:
                                tel.fallback_reason = "reduce_only_sub_notional_after_2022"
                                break
                            cid_r22 = self._adapter.build_client_order_id(
                                clean_sym, side, clamped_rem, True, bucket_tag=f"sm22_{attempt}_{self._next_nonce()}"
                            )
                            try:
                                placed_ord = await self._adapter.place_post_only_limit(
                                    symbol=clean_sym,
                                    side=side,
                                    qty=clamped_rem,
                                    price=limit_px,
                                    reduce_only=True,
                                    client_order_id=cid_r22,
                                )
                            except Exception as r22_err:
                                if _is_post_only_reject_5022(r22_err):
                                    tel.post_only_rejects_5022 += 1
                                    tel.fallback_reason = "post_only_5022"
                                    await self._sleep_fn(eff_cfg.post_only_backoff_sec)
                                    continue
                                self._logger.warning(f"⚠️ [{clean_sym}] GTX retry після -2022 не вдався: {r22_err}")
                                tel.fallback_reason = "gtx_2022_retry_error"
                                break
                        else:
                            self._logger.warning(f"⚠️ [{clean_sym}] GTX attempt {attempt} помилка: {place_err}")
                            tel.fallback_reason = "gtx_place_error"
                            break

                    if not isinstance(placed_ord, dict):
                        continue

                    f_q0, f_px0, f_fee0, st0, oid = _extract_fill_tuple(placed_ord, limit_px)
                    if st0 in ("expired", "rejected", "canceled") and f_q0 <= 0.0:
                        # Binance GTX може повернути status='EXPIRED' замість HTTP -5022
                        tel.post_only_rejects_5022 += 1
                        tel.fallback_reason = "post_only_expired_5022"
                        await self._sleep_fn(eff_cfg.post_only_backoff_sec)
                        continue

                    if st0 in ("closed", "filled") and f_q0 > 0.0:
                        _record_maker_fill(oid or f"imm_{attempt}", f_q0, f_px0, f_fee0)
                        if step_floor_qty(max(0.0, target_qty - (cum_maker_qty + cum_taker_qty)), step_size) < min_qty:
                            break
                        continue

                    if not oid:
                        break
                    active_limit_order_id = oid
                    attempt_deadline = min(order_deadline, self._clock_fn() + float(eff_cfg.poll_sec))
                    filled_in_poll = False

                    while self._clock_fn() < attempt_deadline:
                        sleep_slice = min(float(eff_cfg.poll_interval_sec), max(0.01, attempt_deadline - self._clock_fn()))
                        await self._sleep_fn(sleep_slice)

                        chk_ord = await self._adapter.fetch_order_by_id(clean_sym, oid)
                        f_qc, f_pxc, f_feec, st_c, _ = _extract_fill_tuple(chk_ord, limit_px)
                        if st_c in ("closed", "filled"):
                            _record_maker_fill(oid, f_qc if f_qc > 0.0 else rem_qty, f_pxc, f_feec)
                            active_limit_order_id = None
                            filled_in_poll = True
                            break
                        if st_c in ("canceled", "expired", "rejected"):
                            if f_qc > 0.0:
                                _record_maker_fill(oid, f_qc, f_pxc, f_feec)
                            active_limit_order_id = None
                            filled_in_poll = True
                            break

                        # Перевірка свіжого BBO на adverse drift та необхідність reprice
                        poll_bbo = await self._adapter.fetch_bbo_quote(clean_sym, fallback_price=cur_mid)
                        cur_bbo = poll_bbo
                        p_mid = poll_bbo.mid if poll_bbo.mid > 0 else cur_mid
                        drift_now = side_sign * (p_mid - arrival_mid) / max(arrival_mid, 1e-12) * 10_000.0
                        if drift_now > float(eff_cfg.max_drift_bps):
                            tel.drift_abort = True
                            tel.fallback_reason = "adverse_drift_cap"
                            await _cancel_and_harvest_limit(oid)
                            break

                        passive_now = poll_bbo.bid if side == "buy" else poll_bbo.ask
                        if passive_now > 0.0 and abs(passive_now - limit_px) >= reprice_threshold:
                            tel.fallback_reason = "reprice_l1_shift"
                            await _cancel_and_harvest_limit(oid)
                            break

                    if tel.drift_abort:
                        break

                    if not filled_in_poll and active_limit_order_id == oid:
                        tel.fallback_reason = tel.fallback_reason or "poll_timeout"
                        await _cancel_and_harvest_limit(oid)

                    if step_floor_qty(max(0.0, target_qty - (cum_maker_qty + cum_taker_qty)), step_size) < min_qty:
                        break

            # Fallback після циклу (або прямий MARKET при force_market / малих номіналах / вимкненому Smart Maker)
            if terminal_2022_status is None and not dust_clean_exit:
                rem_after_chase = step_floor_qty(max(0.0, target_qty - (cum_maker_qty + cum_taker_qty)), step_size)
                if rem_after_chase >= min_qty:
                    fb_bbo = await self._adapter.fetch_bbo_quote(clean_sym, fallback_price=arrival_mid)
                    fb_px = (fb_bbo.ask if side == "buy" else fb_bbo.bid) or arrival_mid
                    # Асиметричне правило minNotional перед MARKET fallback:
                    # - reduceOnly=False і < ex_min_notional -> чистий вихід (0 помилок -4164!)
                    # - reduceOnly=True і >= min_qty -> дозволяємо MARKET reduceOnly навіть якщо < ex_min_notional!
                    if (not reduce_only) and (rem_after_chase * fb_px) < ex_min_notional:
                        tel.fallback_reason = tel.fallback_reason or "residual_below_min_notional_entry"
                    else:
                        mk_fb_cid = self._adapter.build_client_order_id(
                            clean_sym, side, rem_after_chase, reduce_only, bucket_tag=f"smfb_{self._next_nonce()}"
                        )
                        m_ord: Optional[Dict[str, Any]] = None
                        try:
                            m_ord = await self._adapter.place_market_order(
                                symbol=clean_sym,
                                side=side,
                                qty=rem_after_chase,
                                reduce_only=reduce_only,
                                client_order_id=mk_fb_cid,
                            )
                        except Exception as m_err:
                            if reduce_only and _is_reduce_only_reject_2022(m_err):
                                live_q2 = await self._adapter.fetch_live_position_qty(clean_sym)
                                if live_q2 is None:
                                    terminal_2022_status = "FAILED_2022_RETRY"
                                elif abs(live_q2) < min_qty:
                                    await self._adapter.cancel_symbol_orders_capture_sl(clean_sym)
                                    terminal_2022_status = "ALREADY_CLOSED_2022"
                                elif (live_q2 > 0 and side != "sell") or (live_q2 < 0 and side != "buy"):
                                    terminal_2022_status = "FAILED_2022_SIDE_MISMATCH"
                                else:
                                    cap_sl2 = await self._adapter.cancel_symbol_orders_capture_sl(clean_sym)
                                    if cap_sl2 > 0.0 and captured_sl_px <= 0.0:
                                        captured_sl_px = cap_sl2
                                    sl_stripped_during_chase = True
                                    clamped_m = step_floor_qty(min(rem_after_chase, abs(live_q2)), step_size)
                                    if clamped_m >= min_qty:
                                        mk_r22_cid = self._adapter.build_client_order_id(
                                            clean_sym, side, clamped_m, True, bucket_tag=f"smfb22_{self._next_nonce()}"
                                        )
                                        try:
                                            m_ord = await self._adapter.place_market_order(
                                                symbol=clean_sym,
                                                side=side,
                                                qty=clamped_m,
                                                reduce_only=True,
                                                client_order_id=mk_r22_cid,
                                            )
                                        except Exception as m2_err:
                                            self._logger.error(f"🚨 [{clean_sym}] MARKET reduceOnly retry після -2022 не вдався: {m2_err}")
                                            terminal_2022_status = "FAILED_2022_RETRY"
                            else:
                                self._logger.error(f"🚨 [{clean_sym}] MARKET fallback помилка: {m_err}")
                                tel.fallback_reason = tel.fallback_reason or "market_fallback_error"

                        if isinstance(m_ord, dict):
                            mq, mpx, mfee, _mst, moid = _extract_fill_tuple(m_ord, fb_px)
                            if mq <= 0.0 and m_ord.get("filled") is None:
                                mq = rem_after_chase
                                mpx = mpx if mpx > 0.0 else fb_px
                            if mq > 0.0:
                                _record_taker_fill(moid or f"mkt_{self._next_nonce()}", mq, mpx, mfee)

        except BaseException:
            aborted_by_exception = True
            raise
        finally:
            # 1) Примусово скасовуємо активну лімітку, якщо вона ще висить на біржі, і зчитуємо фінальний filled
            if active_limit_order_id is not None:
                lingering_id = active_limit_order_id
                try:
                    await _cancel_and_harvest_limit(lingering_id)
                except BaseException as fin_c_err:
                    self._logger.error(f"🚨 [{clean_sym}] Помилка аварійного скасування лімітки {lingering_id} у finally: {fin_c_err}")
                    active_limit_order_id = None

            # 2) Знімаємо символ із лока активних chase-ордерів
            self._active_chase_symbols.discard(clean_sym)

            # 3) Гарантовано перевіряємо/перевиставляємо STOP_MARKET для відкритої позиції, якщо SL знімався або стався збій
            eff_sl = float(active_sl_price or 0.0) if float(active_sl_price or 0.0) > 0.0 else captured_sl_px
            if eff_sl > 0.0 and (sl_stripped_during_chase or aborted_by_exception or reduce_only):
                try:
                    live_rem = await self._adapter.fetch_live_position_qty(clean_sym)
                    if live_rem is not None and abs(live_rem) >= min_qty:
                        ok_sl, _ = await self._adapter.place_or_update_stop_loss_ex(clean_sym, live_rem, eff_sl)
                        if ok_sl:
                            tel.sl_rearmed_after_2022 = True
                except BaseException as fin_sl_err:
                    self._logger.error(f"🚨 [{clean_sym}] Помилка відновлення STOP_MARKET у finally: {fin_sl_err}")

        # Фіналізація агрегованого результату та розрахунку Implementation Shortfall
        tot_filled = cum_maker_qty + cum_taker_qty
        tel.latency_ms = round(max(0.0, (self._clock_fn() - t_start) * 1000.0), 1)
        tel.maker_filled_qty = round(cum_maker_qty, 8)
        tel.taker_filled_qty = round(cum_taker_qty, 8)

        if tot_filled <= 0.0:
            tel.exec_mode = "smart_maker" if use_passive_chase else "market_direct"
            tel.order_status = terminal_2022_status or "REJECTED"
            return SmartMakerResult(dto=None, telemetry=tel)

        avg_fill_px = (cum_maker_cost + cum_taker_cost) / tot_filled
        mk_ratio = cum_maker_qty / tot_filled
        if not use_passive_chase and tel.chase_attempts == 0:
            exec_mode_str = "market_direct"
        elif cum_taker_qty > 1e-12:
            exec_mode_str = "market_fallback"
        else:
            exec_mode_str = "smart_maker"

        eff_fee_usd, eff_fee_bps, is_bps = compute_effective_fee_and_is_bps(
            side=side_up,
            arrival_mid=arrival_mid,
            avg_fill_price=avg_fill_px,
            maker_filled_qty=cum_maker_qty,
            taker_filled_qty=cum_taker_qty,
            explicit_fee_usdt=explicit_fee_sum,
            has_complete_explicit_fee=(any_fill_seen and all_fills_had_explicit_fee),
            vip0_maker_bps=eff_cfg.vip0_maker_fee_bps,
            vip0_taker_bps=eff_cfg.vip0_taker_fee_bps,
        )
        raw_slip_bps = side_sign * (avg_fill_px - arrival_mid) / max(arrival_mid, 1e-12) * 10_000.0
        status_str = "FILLED" if tot_filled >= (target_qty - min_qty * 0.5) else "PARTIAL"

        tel.exec_mode = exec_mode_str
        tel.avg_fill_price = float(avg_fill_px)
        tel.maker_fill_ratio = round(float(mk_ratio), 4)
        tel.fee_usdt = eff_fee_usd
        tel.effective_fee_bps = eff_fee_bps
        tel.implementation_shortfall_bps = is_bps
        tel.order_status = status_str

        dto = OrderExecutionDTO(
            symbol=clean_sym,
            side=side_up,
            executed_qty=round(tot_filled, 8),
            avg_price=float(avg_fill_px),
            fee_usdt=eff_fee_usd,
            realized_pnl_est=float(realized_pnl_est),
            order_id=last_order_id or None,
            note=note,
            maker_qty=round(cum_maker_qty, 8),
            taker_qty=round(cum_taker_qty, 8),
            arrival_price=float(arrival_mid),
            arrival_mid_px=float(arrival_mid),
            spread_bps=tel.bbo_spread_bps,
            slippage_bps=round(float(raw_slip_bps), 3),
            latency_ms=tel.latency_ms,
            is_maker=bool(cum_maker_qty > 0.0 and cum_taker_qty <= 1e-12),
            maker_fallback_used=bool(cum_taker_qty > 1e-12 and tel.chase_attempts > 0),
            order_status=status_str,
        )
        return SmartMakerResult(dto=dto, telemetry=tel)


class CcxtSmartMakerAdapter:
    """Легкий асинхронний адаптер поверх `ExchangeCcxtService` (використовує L1 `bookTicker` без `fetch_order_book`)."""

    __slots__ = ("_svc", "_ws_bbo_getter")

    def __init__(
        self,
        exchange_svc: Any,
        ws_bbo_getter: Optional[Callable[[str], Optional[BBOQuote]]] = None,
    ) -> None:
        self._svc = exchange_svc
        self._ws_bbo_getter = ws_bbo_getter

    async def fetch_bbo_quote(self, symbol: str, fallback_price: float) -> BBOQuote:
        clean = ccxt_to_symbol(symbol)
        if self._ws_bbo_getter is not None:
            ws_q = self._ws_bbo_getter(clean)
            if ws_q is not None and ws_q.bid > 0.0 and ws_q.ask > 0.0 and (time.time() - ws_q.timestamp) <= 2.5:
                return ws_q
        return await asyncio.to_thread(self._fetch_bbo_sync, clean, fallback_price)

    def _fetch_bbo_sync(self, clean_sym: str, fallback_price: float) -> BBOQuote:
        from app.core.config import symbol_to_ccxt

        ex = getattr(self._svc, "_exchange", None)
        now = time.time()
        if ex is None:
            return BBOQuote(bid=float(fallback_price), ask=float(fallback_price), timestamp=now)

        # 1. Прямий L1 bookTicker Binance USD-M (вага 1, без завантаження стакана L2!)
        if hasattr(ex, "fapiPublicGetTickerBookTicker") and not hasattr(ex, "_mock_name"):
            try:
                bt = ex.fapiPublicGetTickerBookTicker({"symbol": clean_sym})
                if isinstance(bt, dict):
                    b = float(bt.get("bidPrice") or 0.0)
                    a = float(bt.get("askPrice") or 0.0)
                    if b > 0.0 and a > 0.0:
                        return BBOQuote(bid=b, ask=a, timestamp=now)
            except Exception:
                pass

        # 2. Універсальний легкий ticker CCXT (та сумісність із тестовими моками)
        ccxt_sym = symbol_to_ccxt(clean_sym)
        if hasattr(ex, "fetch_ticker"):
            try:
                tk = ex.fetch_ticker(ccxt_sym)
                if isinstance(tk, dict):
                    b = float(tk.get("bid") or (tk.get("info") or {}).get("bidPrice") or 0.0)
                    a = float(tk.get("ask") or (tk.get("info") or {}).get("askPrice") or 0.0)
                    if b > 0.0 and a > 0.0:
                        return BBOQuote(bid=b, ask=a, timestamp=now)
            except Exception:
                pass

        return BBOQuote(bid=float(fallback_price), ask=float(fallback_price), timestamp=now)

    async def place_post_only_limit(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict[str, Any]:
        from app.core.config import symbol_to_ccxt

        clean = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean)
        params: Dict[str, Any] = {
            "timeInForce": "GTX",
            "postOnly": True,
            "newClientOrderId": client_order_id,
        }
        if reduce_only:
            params["reduceOnly"] = True
        return await asyncio.to_thread(
            self._svc._exchange.create_order,
            symbol=ccxt_sym,
            type="limit",
            side=side.lower(),
            amount=qty,
            price=price,
            params=params,
        )

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict[str, Any]:
        from app.core.config import symbol_to_ccxt

        clean = ccxt_to_symbol(symbol)
        ccxt_sym = symbol_to_ccxt(clean)
        params: Dict[str, Any] = {
            "newClientOrderId": client_order_id,
            "newOrderRespType": "RESULT",
        }
        if reduce_only:
            params["reduceOnly"] = True
        return await asyncio.to_thread(
            self._svc._exchange.create_market_order,
            ccxt_sym,
            side.lower(),
            qty,
            params=params,
        )

    async def cancel_order_by_id(self, symbol: str, order_id: str) -> None:
        from app.core.config import symbol_to_ccxt

        ccxt_sym = symbol_to_ccxt(ccxt_to_symbol(symbol))
        await asyncio.to_thread(self._svc._exchange.cancel_order, order_id, ccxt_sym)

    async def fetch_order_by_id(self, symbol: str, order_id: str) -> Optional[Dict[str, Any]]:
        from app.core.config import symbol_to_ccxt

        ccxt_sym = symbol_to_ccxt(ccxt_to_symbol(symbol))
        res = await asyncio.to_thread(self._svc._exchange.fetch_order, order_id, ccxt_sym)
        return res if isinstance(res, dict) else None

    async def fetch_live_position_qty(self, symbol: str) -> Optional[float]:
        from app.core.config import symbol_to_ccxt

        clean = ccxt_to_symbol(symbol)
        return await asyncio.to_thread(self._svc._fetch_live_symbol_position_sync, symbol_to_ccxt(clean), clean)

    async def cancel_symbol_orders_capture_sl(self, symbol: str) -> float:
        from app.core.config import symbol_to_ccxt

        clean = ccxt_to_symbol(symbol)
        _, sl_px = await asyncio.to_thread(self._svc._cancel_symbol_orders_with_sl_capture_sync, symbol_to_ccxt(clean), clean)
        return float(sl_px or 0.0)

    async def place_or_update_stop_loss_ex(
        self, symbol: str, position_qty: float, stop_price: float
    ) -> Tuple[bool, str]:
        return await self._svc.place_or_update_stop_loss_ex(ccxt_to_symbol(symbol), position_qty, stop_price)

    def build_client_order_id(
        self, symbol: str, side: str, qty: float, reduce_only: bool, bucket_tag: str
    ) -> str:
        return self._svc.build_client_order_id(symbol, side, qty, reduce_only, bucket_tag=bucket_tag)

    def get_symbol_filters(self, symbol: str) -> Tuple[float, float, float, float]:
        clean = ccxt_to_symbol(symbol)
        min_q, step_sz, min_not, _, _ = settings.get_symbol_spec(clean)
        tick_sz = settings.get_tick_size(clean)
        ex = getattr(self._svc, "_exchange", None)
        markets = getattr(ex, "markets", None) if ex is not None else None
        if isinstance(markets, dict):
            from app.core.config import symbol_to_ccxt

            m = markets.get(symbol_to_ccxt(clean))
            if isinstance(m, dict):
                filters = (m.get("info") or {}).get("filters") or []
                for flt in filters:
                    if not isinstance(flt, dict):
                        continue
                    ft = str(flt.get("filterType") or "")
                    if ft == "PRICE_FILTER" and flt.get("tickSize"):
                        ts_v = float(flt["tickSize"])
                        if ts_v > 0:
                            tick_sz = ts_v
                    elif ft == "LOT_SIZE":
                        if flt.get("stepSize") and float(flt["stepSize"]) > 0:
                            step_sz = float(flt["stepSize"])
                        if flt.get("minQty") and float(flt["minQty"]) > 0:
                            min_q = float(flt["minQty"])
                    elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                        nv = float(flt.get("notional") or flt.get("minNotional") or 0.0)
                        if nv > 0:
                            min_not = nv
        return float(min_q), float(step_sz), float(min_not), float(tick_sz)

