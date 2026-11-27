# -*- coding: utf-8 -*-
"""Детерміновані unit-тести V6.2-B `SmartMakerExecutor` та `Implementation Shortfall` (0 реальних sleep)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

SERVER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from app.core.config import settings
from app.domain.schemas import CoinStateDTO, CoinTargetDTO, ExchangePositionDTO, OrderExecutionDTO, PortfolioTargetDTO
from app.services.database_service import DatabaseService
from app.services.exchange_ccxt_service import ExchangeCcxtService
from app.services.execution_service import MultiAssetExecutionOrchestrator
from app.services.research_lake_service import ResearchLakeService
from app.services.smart_maker_executor import (
    BBOQuote,
    SmartMakerConfig,
    SmartMakerExecutor,
    compute_effective_fee_and_is_bps,
)
from app.services.state_service import StateService
from app.services.ws_sentinel_service import WebSocketSentinelService


class FakeVirtualClock:
    """Детермінований віртуальний годинник для миттєвого проходження poll-циклів у тестах."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now: float = start
        self.sleeps: List[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, dt: float) -> None:
        self.sleeps.append(float(dt))
        self.now += max(0.0, float(dt))
        await asyncio.sleep(0)


class MockSmartMakerAdapter:
    """Керований тестовий адаптер біржі для перевірки всіх граничних станів `SmartMakerExecutor`."""

    def __init__(
        self,
        filters: Tuple[float, float, float, float] = (0.1, 0.1, 5.0, 0.01),
        quotes: Optional[List[BBOQuote]] = None,
    ) -> None:
        self.filters = filters
        self.quotes: List[BBOQuote] = list(quotes or [BBOQuote(bid=99.95, ask=100.05, timestamp=1000.0)])
        self._q_idx = 0
        self.placed_limits: List[Dict[str, Any]] = []
        self.placed_markets: List[Dict[str, Any]] = []
        self.canceled_ids: List[str] = []
        self.fetched_ids: List[str] = []
        self.sl_placements: List[Tuple[str, float, float]] = []
        self.cancel_all_calls: int = 0
        self.captured_sl_to_return: float = 0.0
        self.live_pos_qty: Optional[float] = 0.0

        self.on_place_limit: Optional[Any] = None
        self.on_place_market: Optional[Any] = None
        self.on_cancel_order: Optional[Any] = None
        self.on_fetch_order: Optional[Any] = None

    async def fetch_bbo_quote(self, symbol: str, fallback_price: float) -> BBOQuote:
        if not self.quotes:
            return BBOQuote(bid=fallback_price, ask=fallback_price)
        q = self.quotes[min(self._q_idx, len(self.quotes) - 1)]
        self._q_idx += 1
        return q

    async def place_post_only_limit(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict[str, Any]:
        req = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "reduce_only": reduce_only,
            "client_order_id": client_order_id,
        }
        self.placed_limits.append(req)
        if self.on_place_limit is not None:
            res = self.on_place_limit(req, len(self.placed_limits))
            if asyncio.iscoroutine(res):
                return await res
            return res
        return {
            "id": f"lim_{len(self.placed_limits)}",
            "status": "open",
            "filled": 0.0,
            "average": 0.0,
            "price": price,
        }

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool,
        client_order_id: str,
    ) -> Dict[str, Any]:
        req = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "reduce_only": reduce_only,
            "client_order_id": client_order_id,
        }
        self.placed_markets.append(req)
        if self.on_place_market is not None:
            res = self.on_place_market(req, len(self.placed_markets))
            if asyncio.iscoroutine(res):
                return await res
            return res
        q_last = self.quotes[min(max(0, self._q_idx - 1), len(self.quotes) - 1)]
        fill_px = q_last.ask if side == "buy" else q_last.bid
        return {
            "id": f"mkt_{len(self.placed_markets)}",
            "status": "closed",
            "filled": qty,
            "average": fill_px,
        }

    async def cancel_order_by_id(self, symbol: str, order_id: str) -> None:
        self.canceled_ids.append(order_id)
        if self.on_cancel_order is not None:
            res = self.on_cancel_order(symbol, order_id)
            if asyncio.iscoroutine(res):
                await res

    async def fetch_order_by_id(self, symbol: str, order_id: str) -> Optional[Dict[str, Any]]:
        self.fetched_ids.append(order_id)
        if self.on_fetch_order is not None:
            res = self.on_fetch_order(symbol, order_id, len(self.fetched_ids))
            if asyncio.iscoroutine(res):
                return await res
            return res
        return {"id": order_id, "status": "open", "filled": 0.0, "average": 0.0}

    async def fetch_live_position_qty(self, symbol: str) -> Optional[float]:
        return self.live_pos_qty

    async def cancel_symbol_orders_capture_sl(self, symbol: str) -> float:
        self.cancel_all_calls += 1
        return self.captured_sl_to_return

    async def place_or_update_stop_loss_ex(
        self, symbol: str, position_qty: float, stop_price: float
    ) -> Tuple[bool, str]:
        self.sl_placements.append((symbol, position_qty, stop_price))
        return True, "OK"

    def build_client_order_id(
        self, symbol: str, side: str, qty: float, reduce_only: bool, bucket_tag: str
    ) -> str:
        return ExchangeCcxtService.build_client_order_id(symbol, side, qty, reduce_only, bucket_tag=bucket_tag)

    def get_symbol_filters(self, symbol: str) -> Tuple[float, float, float, float]:
        return self.filters


class TestSmartMakerExecutor(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("TestSmartMaker")
        self.cfg = SmartMakerConfig(
            enabled=True,
            max_attempts=3,
            poll_sec=12.0,
            poll_interval_sec=2.0,
            reprice_bps=3.0,
            max_drift_bps=25.0,
            min_notional_usd=15.0,
            concurrency=4,
        )

    async def test_1_maker_fill_first_attempt_buy_and_sell_is_bps(self) -> None:
        """1. 100% Maker fill на 1-й спробі (BUY та SELL): maker_fill_ratio == 1.0, IS_bps < 0, унікальні CID."""
        clock = FakeVirtualClock()
        # arrival_bid=99.95, arrival_ask=100.05 -> arrival_mid=100.00 (spread 10 bps)
        adapter_buy = MockSmartMakerAdapter(quotes=[BBOQuote(99.95, 100.05)])
        adapter_buy.on_fetch_order = lambda sym, oid, n: {
            "id": oid, "status": "closed", "filled": 1.0, "average": 99.95,
        }
        exec_buy = SmartMakerExecutor(adapter_buy, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res_buy = await exec_buy.execute_smart_maker_order("SOLUSDT", delta_qty=1.0, mark_price=100.0, cfg=self.cfg)

        self.assertIsNotNone(res_buy.dto)
        self.assertEqual(res_buy.telemetry.exec_mode, "smart_maker")
        self.assertEqual(res_buy.telemetry.chase_attempts, 1)
        self.assertEqual(res_buy.telemetry.cancel_count, 0)
        self.assertAlmostEqual(res_buy.telemetry.maker_fill_ratio, 1.0)
        self.assertAlmostEqual(res_buy.telemetry.effective_fee_bps, 2.0)
        # BUY @ 99.95 vs mid 100.00 -> -5.0 bps price improvement + 2.0 bps VIP0 maker fee = -3.0 bps!
        self.assertAlmostEqual(res_buy.telemetry.implementation_shortfall_bps, -3.0, places=3)
        self.assertEqual(len(adapter_buy.placed_markets), 0)

        # SELL @ 100.05 vs mid 100.00 -> -1 * (100.05 - 100.00)/100 * 10000 + 2.0 = -3.0 bps!
        adapter_sell = MockSmartMakerAdapter(quotes=[BBOQuote(99.95, 100.05)])
        adapter_sell.on_fetch_order = lambda sym, oid, n: {
            "id": oid, "status": "closed", "filled": 1.0, "average": 100.05,
        }
        exec_sell = SmartMakerExecutor(adapter_sell, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res_sell = await exec_sell.execute_smart_maker_order("SOLUSDT", delta_qty=-1.0, mark_price=100.0, cfg=self.cfg)
        self.assertIsNotNone(res_sell.dto)
        self.assertAlmostEqual(res_sell.telemetry.maker_fill_ratio, 1.0)
        self.assertAlmostEqual(res_sell.telemetry.implementation_shortfall_bps, -3.0, places=3)
        self.assertNotEqual(
            adapter_buy.placed_limits[0]["client_order_id"],
            adapter_sell.placed_limits[0]["client_order_id"],
        )

    async def test_2_asymmetric_dust_rule_entry_vs_reduce_only(self) -> None:
        """2. Асиметричне правило minNotional: вхід пропускає хвіст < $5 (-4164 guard), reduceOnly=True дозакриває через MARKET."""
        clock = FakeVirtualClock()
        # SOL @ $20.00, min_qty=0.1, min_notional=$5.0. Запит +1.0 SOL ($20 >= $15).
        # Спроба 1 заливає 0.8 SOL ($16), залишається 0.2 SOL ($4.00 < $5.00 minNotional!).
        adapter_in = MockSmartMakerAdapter(
            filters=(0.1, 0.1, 5.0, 0.01),
            quotes=[BBOQuote(19.99, 20.01)],
        )
        adapter_in.on_fetch_order = lambda sym, oid, n: (
            {"id": oid, "status": "open", "filled": 0.0} if n < 6 else {"id": oid, "status": "canceled", "filled": 0.8, "average": 19.99}
        )
        exec_in = SmartMakerExecutor(adapter_in, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res_in = await exec_in.execute_smart_maker_order(
            "SOLUSDT", delta_qty=1.0, mark_price=20.0, reduce_only=False, cfg=self.cfg
        )
        self.assertIsNotNone(res_in.dto)
        self.assertAlmostEqual(res_in.dto.executed_qty, 0.8)
        self.assertEqual(len(adapter_in.placed_limits), 1)
        self.assertEqual(len(adapter_in.placed_markets), 0)  # Жодного MARKET на $4.00 хвості входу!

        # На закритті (reduceOnly=True): ті самі 0.2 SOL ($4.00 < $5.00, але 0.2 >= min_qty=0.1) ДОЗАКРИВАЮТЬСЯ через MARKET reduceOnly!
        adapter_out = MockSmartMakerAdapter(
            filters=(0.1, 0.1, 5.0, 0.01),
            quotes=[BBOQuote(19.99, 20.01)],
        )
        adapter_out.live_pos_qty = 0.0
        adapter_out.on_fetch_order = lambda sym, oid, n: (
            {"id": oid, "status": "open", "filled": 0.0} if n < 6 else {"id": oid, "status": "canceled", "filled": 0.8, "average": 20.01}
        )
        exec_out = SmartMakerExecutor(adapter_out, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res_out = await exec_out.execute_smart_maker_order(
            "SOLUSDT", delta_qty=-1.0, mark_price=20.0, reduce_only=True, cfg=self.cfg
        )
        self.assertIsNotNone(res_out.dto)
        self.assertAlmostEqual(res_out.dto.executed_qty, 1.0)
        self.assertAlmostEqual(res_out.telemetry.maker_filled_qty, 0.8)
        self.assertAlmostEqual(res_out.telemetry.taker_filled_qty, 0.2)
        self.assertEqual(len(adapter_out.placed_markets), 1)
        self.assertTrue(adapter_out.placed_markets[0]["reduce_only"])
        self.assertAlmostEqual(adapter_out.placed_markets[0]["qty"], 0.2)

    async def test_3_cancel_race_condition_2011_zero_double_fill(self) -> None:
        """3. Race condition -2011 на cancel_order: ордер залився в момент скасування -> fetch_order фіксує 100% fill, 0 MARKET!"""
        clock = FakeVirtualClock()
        adapter = MockSmartMakerAdapter(quotes=[BBOQuote(99.95, 100.05)])

        def _cancel_raises_2011(sym: str, oid: str) -> None:
            raise Exception('binance {"code":-2011,"msg":"Unknown order sent."}')

        def _fetch_after_race(sym: str, oid: str, call_n: int) -> Dict[str, Any]:
            # Під час 6 опитувань ордер ще open, а в момент cancel_order він виконався на 100% (2.0)!
            if call_n <= 6:
                return {"id": oid, "status": "open", "filled": 0.0, "average": 0.0}
            return {"id": oid, "status": "closed", "filled": 2.0, "average": 99.95}

        adapter.on_cancel_order = _cancel_raises_2011
        adapter.on_fetch_order = _fetch_after_race

        executor = SmartMakerExecutor(adapter, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res = await executor.execute_smart_maker_order("SOLUSDT", delta_qty=2.0, mark_price=100.0, cfg=self.cfg)

        self.assertIsNotNone(res.dto)
        self.assertAlmostEqual(res.dto.executed_qty, 2.0)
        self.assertAlmostEqual(res.telemetry.maker_filled_qty, 2.0)
        self.assertAlmostEqual(res.telemetry.taker_filled_qty, 0.0)
        self.assertEqual(res.telemetry.chase_attempts, 1)
        self.assertEqual(len(adapter.placed_markets), 0)  # НУЛЬ подвійного виконання!

    async def test_4_btc_milli_tick_no_reprice_then_3bps_reprice_and_vwap_fallback(self) -> None:
        """4. BTCUSDT: зсув 2 тіки ($0.20 < $27.0 = 3 bps) НЕ скасовує ордер; зсув >= 3 bps робить reprice + точний VWAP fallback."""
        clock = FakeVirtualClock()
        # BTC @ $90,000 (min_qty=0.001, step=0.001, min_notional=$100, tick=$0.10). Поріг reprice = max(0.1, 90000*3e-4) = $27.0.
        quotes = [
            BBOQuote(90_000.0, 90_000.5),  # arrival BBO (mid = 90000.25)
            BBOQuote(90_000.2, 90_000.7),  # Poll 1 (+2 тіки = +$0.20 < $27.0) -> НЕ робимо reprice!
            BBOQuote(90_030.0, 90_030.5),  # Poll 2 (+$30.0 >= $27.0, але < 25 bps = $225) -> Reprice!
            BBOQuote(90_030.0, 90_030.5),  # Attempt 2 arrival quote
            BBOQuote(90_060.0, 90_060.5),  # Attempt 2 poll -> ще +$30 -> Reprice!
            BBOQuote(90_060.0, 90_060.5),  # Attempt 3 arrival quote
            BBOQuote(90_095.0, 90_095.5),  # Attempt 3 poll -> +$35 -> cancel & вичерпано 3 спроби
            BBOQuote(90_039.5, 90_040.0),  # MARKET fallback BBO (ask = 90040.0)
        ]
        adapter = MockSmartMakerAdapter(filters=(0.001, 0.001, 100.0, 0.1), quotes=quotes)

        def _fetch_btc(sym: str, oid: str, n: int) -> Dict[str, Any]:
            # На скасуванні lim_1 віддаємо частковий філ 0.002 BTC @ $90,000.0; залишок 0.002 BTC ($180 >= $100 minNotional)
            if oid == "lim_1" and oid in adapter.canceled_ids:
                return {"id": oid, "status": "canceled", "filled": 0.002, "average": 90_000.0}
            return {"id": oid, "status": "open", "filled": 0.0, "average": 0.0}

        adapter.on_fetch_order = _fetch_btc
        executor = SmartMakerExecutor(adapter, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res = await executor.execute_smart_maker_order("BTCUSDT", delta_qty=0.004, mark_price=90_000.0, cfg=self.cfg)

        self.assertIsNotNone(res.dto)
        # На Poll 1 при +$0.20 скасування НЕ відбулося -> загалом рівно 3 спроби (lim_1 на 2-му полі, lim_2, lim_3)
        self.assertEqual(res.telemetry.chase_attempts, 3)
        self.assertEqual(adapter.fetched_ids.count("lim_1"), 3)  # Poll 1 (open), Poll 2 (open), Post-Cancel harvest!
        self.assertAlmostEqual(res.telemetry.maker_filled_qty, 0.002)
        self.assertAlmostEqual(res.telemetry.taker_filled_qty, 0.002)
        self.assertAlmostEqual(res.telemetry.maker_fill_ratio, 0.5)
        # Обсягово-зважена середня: 0.5 * 90000.0 + 0.5 * 90040.0 = 90020.0; комісія VIP0: 0.5*2 + 0.5*5 = 3.5 bps
        self.assertAlmostEqual(res.dto.avg_price, 90_020.0, places=4)
        self.assertAlmostEqual(res.telemetry.effective_fee_bps, 3.5, places=4)
        self.assertEqual(res.telemetry.exec_mode, "market_fallback")

    async def test_5_post_only_5022_rejects_and_unique_client_order_ids(self) -> None:
        """5. Обробка -5022 (виняток та status=EXPIRED) + унікальні clientOrderId на кожній спробі (0 -4116)."""
        clock = FakeVirtualClock()
        adapter = MockSmartMakerAdapter(quotes=[
            BBOQuote(99.95, 100.05),
            BBOQuote(99.96, 100.06),
            BBOQuote(99.97, 100.07),
        ])

        def _place_5022_seq(req: Dict[str, Any], attempt_idx: int) -> Dict[str, Any]:
            if attempt_idx == 1:
                raise Exception('binance {"code":-5022,"msg":"Due to the order could not be executed as maker, the Post Only order will be rejected."}')
            if attempt_idx == 2:
                return {"id": "lim_exp_2", "status": "EXPIRED", "filled": 0.0}
            return {"id": "lim_ok_3", "status": "closed", "filled": 1.0, "average": req["price"]}

        adapter.on_place_limit = _place_5022_seq
        executor = SmartMakerExecutor(adapter, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res = await executor.execute_smart_maker_order("SOLUSDT", delta_qty=1.0, mark_price=100.0, cfg=self.cfg)

        self.assertIsNotNone(res.dto)
        self.assertEqual(res.telemetry.post_only_rejects_5022, 2)
        self.assertEqual(res.telemetry.chase_attempts, 3)
        self.assertAlmostEqual(res.telemetry.maker_fill_ratio, 1.0)
        cids = [x["client_order_id"] for x in adapter.placed_limits]
        self.assertEqual(len(cids), 3)
        self.assertEqual(len(set(cids)), 3)  # Усі 3 clientOrderId строго унікальні!

    async def test_6_reduce_only_2022_strips_sl_continues_chase_and_rearms_sl_in_finally(self) -> None:
        """6. -2022 через зайняту квоту STOP_MARKET: зняття SL -> продовження Maker chase -> гарантоване повернення SL на залишок."""
        clock = FakeVirtualClock()
        adapter = MockSmartMakerAdapter(quotes=[BBOQuote(99.95, 100.05)])
        adapter.live_pos_qty = 10.0
        adapter.captured_sl_to_return = 88.0

        def _place_2022_then_ok(req: Dict[str, Any], call_n: int) -> Dict[str, Any]:
            if call_n == 1:
                raise Exception('binance {"code":-2022,"msg":"ReduceOnly Order is rejected."}')
            # Після зняття SL повтор у межах тієї ж спроби успішний, і після філу позиція стає +6.0
            adapter.live_pos_qty = 6.0
            return {"id": "lim_trim_ok", "status": "closed", "filled": 4.0, "average": 100.05}

        adapter.on_place_limit = _place_2022_then_ok
        executor = SmartMakerExecutor(adapter, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res = await executor.execute_smart_maker_order(
            "SOLUSDT", delta_qty=-4.0, mark_price=100.0, reduce_only=True, active_sl_price=88.0, cfg=self.cfg
        )

        self.assertIsNotNone(res.dto)
        self.assertAlmostEqual(res.dto.executed_qty, 4.0)
        self.assertAlmostEqual(res.telemetry.maker_fill_ratio, 1.0)
        self.assertEqual(adapter.cancel_all_calls, 1)
        self.assertEqual(res.telemetry.chase_attempts, 1)
        self.assertTrue(res.telemetry.sl_rearmed_after_2022)
        self.assertEqual(adapter.sl_placements, [("SOLUSDT", 6.0, 88.0)])

    async def test_7_cancelled_error_finally_cancels_limit_unlocks_symbol_and_rearms_sl(self) -> None:
        """7. Аварійний finally при asyncio.CancelledError + блокування втручання WSSentinel під час активного chase."""
        adapter = MockSmartMakerAdapter(quotes=[BBOQuote(99.95, 100.05)])
        adapter.live_pos_qty = 5.0
        entered_poll = asyncio.Event()
        hold_poll = asyncio.Event()

        async def _blocking_sleep(dt: float) -> None:
            entered_poll.set()
            await hold_poll.wait()

        active_set: set[str] = set()
        executor = SmartMakerExecutor(
            adapter, self.logger, active_chase_symbols=active_set, sleep_fn=_blocking_sleep
        )

        # Налаштовуємо WSSentinel, щоб перевірити, що під час активного chase він НЕ чіпає SL символа!
        st = StateService()
        st.coins["SOLUSDT"] = CoinStateDTO(symbol="SOLUSDT", current_pos_qty=5.0, entry_price=90.0, is_breakeven=False)
        ex_mock = MagicMock()
        ex_mock.is_symbol_chasing = executor.is_symbol_chasing
        ex_mock.place_or_update_stop_loss = AsyncMock(return_value=True)
        ws = WebSocketSentinelService(self.logger, st, ex_mock)
        ws._mark_prices["SOLUSDT"] = 105.0
        ws.update_symbol_atr("SOLUSDT", 2.0)

        task = asyncio.create_task(
            executor.execute_smart_maker_order(
                "SOLUSDT", delta_qty=-2.0, mark_price=100.0, reduce_only=True, active_sl_price=88.0, cfg=self.cfg
            )
        )
        await entered_poll.wait()

        # Поки chase активний: символ у active_chase_symbols, і WSSentinel пропускає його!
        self.assertIn("SOLUSDT", active_set)
        await ws._check_breakeven_and_ratchet()
        ex_mock.place_or_update_stop_loss.assert_not_awaited()

        # Скасовуємо таску (симуляція shutdown / таймауту) -> спрацьовує куленепробивний finally!
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(adapter.canceled_ids, ["lim_1"])
        self.assertNotIn("SOLUSDT", active_set)
        self.assertEqual(adapter.sl_placements, [("SOLUSDT", 5.0, 88.0)])

    async def test_8_adverse_drift_cap_aborts_immediately_to_market(self) -> None:
        """8. Adverse Drift Cap (> 25 bps): миттєвий drift_abort=True, скасування лімітки та негайний MARKET fallback."""
        clock = FakeVirtualClock()
        # arrival_mid = 100.00; на 1-му опитуванні ціна тікає вгору до 100.30 (+30 bps > 25 bps для BUY!)
        quotes = [
            BBOQuote(99.95, 100.05),   # arrival mid = 100.00
            BBOQuote(100.25, 100.35),  # Poll 1 mid = 100.30 (+30 bps > 25 bps!) -> drift_abort!
            BBOQuote(100.25, 100.35),  # MARKET fallback BBO
        ]
        adapter = MockSmartMakerAdapter(quotes=quotes)
        executor = SmartMakerExecutor(adapter, self.logger, clock_fn=clock, sleep_fn=clock.sleep)
        res = await executor.execute_smart_maker_order("SOLUSDT", delta_qty=1.0, mark_price=100.0, cfg=self.cfg)

        self.assertIsNotNone(res.dto)
        self.assertTrue(res.telemetry.drift_abort)
        self.assertEqual(res.telemetry.chase_attempts, 1)  # Не витрачав спроби 2 та 3!
        self.assertEqual(res.telemetry.cancel_count, 1)
        self.assertEqual(res.telemetry.exec_mode, "market_fallback")
        self.assertAlmostEqual(res.telemetry.taker_filled_qty, 1.0)
        self.assertEqual(len(adapter.placed_markets), 1)

    async def test_9_two_phase_order_flip_perimeter_semaphore_and_audit_aggregation(self) -> None:
        """9. Фаза 1 (виходи/тріми + 1-ша нога flip) строго до Фази 2; Semaphore(2); периметр безпеки; агрегація IS у звіті."""
        from scripts.audit_report import aggregate_order_lifecycle_telemetry

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            db = DatabaseService(db_path=str(tmp_dir / "t.db"))
            await db.init()
            lake = ResearchLakeService(lake_dir=str(tmp_dir / "lake"), max_mb=5)

            st = StateService()
            st.coins = {
                "ETHUSDT": CoinStateDTO(symbol="ETHUSDT", current_pos_qty=0.10, entry_price=2000.0, active_sl_price=1800.0),
                "AVAXUSDT": CoinStateDTO(symbol="AVAXUSDT", current_pos_qty=4.0, entry_price=25.0, active_sl_price=20.0),
                "SOLUSDT": CoinStateDTO(symbol="SOLUSDT", current_pos_qty=1.0, entry_price=100.0, active_sl_price=88.0),
                "LINKUSDT": CoinStateDTO(symbol="LINKUSDT", current_pos_qty=0.0),
                "NEARUSDT": CoinStateDTO(symbol="NEARUSDT", current_pos_qty=0.0),
                "SUIUSDT": CoinStateDTO(symbol="SUIUSDT", current_pos_qty=0.0),
            }

            call_events: List[Tuple[str, str, bool, bool]] = []
            in_flight = 0
            max_in_flight = 0

            async def _fake_exec(**kwargs: Any) -> OrderExecutionDTO:
                nonlocal in_flight, max_in_flight
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                sym = kwargs["symbol"]
                ro = bool(kwargs.get("reduce_only", False))
                sm = bool(kwargs.get("allow_smart_maker", False))
                call_events.append(("START", sym, ro, sm))
                await asyncio.sleep(0.01)
                call_events.append(("END", sym, ro, sm))
                in_flight -= 1
                dq = float(kwargs["delta_qty"])
                px = float(kwargs["mark_price"])
                return OrderExecutionDTO(
                    symbol=sym,
                    side="BUY" if dq > 0 else "SELL",
                    executed_qty=abs(dq),
                    avg_price=px * (0.9997 if dq > 0 else 1.0003),
                    maker_qty=abs(dq) if sm else 0.0,
                    taker_qty=0.0 if sm else abs(dq),
                    arrival_mid_px=px,
                    is_maker=sm,
                )

            ex = MagicMock()
            ex.fetch_account_snapshot = AsyncMock(return_value=(1000.0, 0.0, {
                "ETHUSDT": ExchangePositionDTO(symbol="ETHUSDT", contracts_qty=0.10, entry_price=2000.0),
                "AVAXUSDT": ExchangePositionDTO(symbol="AVAXUSDT", contracts_qty=4.0, entry_price=25.0),
                "SOLUSDT": ExchangePositionDTO(symbol="SOLUSDT", contracts_qty=1.0, entry_price=100.0),
            }, True))
            ex.fetch_funding_rates = AsyncMock(return_value={})
            ex.fetch_market_microstructure = AsyncMock(return_value={})
            ex.safe_price = lambda s, p: round(float(p), 4)
            ex.safe_amount = lambda s, q: round(float(q), 4)
            ex.place_or_update_stop_loss_ex = AsyncMock(return_value=(True, "OK"))
            ex.place_or_update_stop_loss = AsyncMock(return_value=True)
            ex.cancel_symbol_orders = AsyncMock(return_value=True)
            ex.get_last_order_diag = lambda s: {}
            ex.execute_smart_rebalance_order = AsyncMock(side_effect=_fake_exec)

            # ETH -> 0 (close), AVAX +4 -> +2 (trim), SOL +1 -> -1 (flip: Leg1 у Фазі 1, Leg2 у Фазі 2), LINK/NEAR/SUI -> нові входи
            port_dto = PortfolioTargetDTO(
                cartridge_name="v6_multi_sleeve",
                architecture="MultiSleeve",
                candle_timestamp="2026-11-27T00:00:00+00:00",
                market_breadth=0.2,
                news_sentiment=0.0,
                total_gross_leverage=0.50,
                net_leverage=0.0,
                targets={
                    "ETHUSDT": CoinTargetDTO("ETHUSDT", 0.0, 0.0, 0, 0.0, 0, 0, 0, 0, 0, 2000.0, 40.0, dominant_book="V2_MOMENTUM", sl_atr_mult=12.0),
                    "AVAXUSDT": CoinTargetDTO("AVAXUSDT", 0.05, 0.05, 1, 0.5, 0, 0, 0, 0, 0, 25.0, 1.0, dominant_book="V2_MOMENTUM", sl_atr_mult=12.0),
                    "SOLUSDT": CoinTargetDTO("SOLUSDT", -0.10, -0.10, -1, -0.8, 0, 0, 0, 0, 0, 100.0, 3.0, dominant_book="V2_MOMENTUM", sl_atr_mult=4.8),
                    "LINKUSDT": CoinTargetDTO("LINKUSDT", 0.08, 0.08, 1, 0.7, 0, 0, 0, 0, 0, 20.0, 0.8, dominant_book="V2_MOMENTUM", sl_atr_mult=12.0),
                    "NEARUSDT": CoinTargetDTO("NEARUSDT", -0.08, -0.08, -1, -0.7, 0, 0, 0, 0, 0, 5.0, 0.2, dominant_book="V2_MOMENTUM", sl_atr_mult=4.8),
                    "SUIUSDT": CoinTargetDTO("SUIUSDT", 0.07, 0.07, 1, 0.6, 0, 0, 0, 0, 0, 2.0, 0.1, dominant_book="V2_MOMENTUM", sl_atr_mult=12.0),
                },
                extra_telemetry={"sleeve_books": {k: "SLEEVE_B" for k in st.coins}},
            )

            import pandas as pd
            df_stub = pd.DataFrame({"timestamp": ["2026-11-27 00:00:00"] * 370, "close": [100.0] * 370})
            mdata = MagicMock()
            mdata.fetch_synchronized_candles = AsyncMock(return_value={k: df_stub for k in ("BTCUSDT", *st.coins.keys())})

            cart_loader = MagicMock()
            cart_loader.active_name = "v6_multi_sleeve"
            cart_loader.cartridge.supported_symbols = tuple(st.coins.keys())
            cart_loader.cartridge.architecture_name = "MultiSleeve"
            cart_loader.cartridge.compute_portfolio_targets = MagicMock(return_value=port_dto)

            orch = MultiAssetExecutionOrchestrator(
                logger=self.logger, state_service=st, db_service=db, exchange_service=ex,
                cartridge_service=cart_loader, online_learner=MagicMock(), news_service=MagicMock(),
                market_data_service=mdata,
            )

            orig_sm = settings.SMART_MAKER_CHASE_ENABLED
            orig_conc = settings.SMART_MAKER_CONCURRENCY
            orig_demo = settings.USE_DEMO_TRADING
            object.__setattr__(settings, "SMART_MAKER_CHASE_ENABLED", True)
            object.__setattr__(settings, "SMART_MAKER_CONCURRENCY", 2)
            object.__setattr__(settings, "USE_DEMO_TRADING", False)
            try:
                with patch.object(StateService, "save_snapshot", MagicMock()), patch(
                    "app.services.execution_service.research_lake", lake
                ):
                    await orch.run_step(force_recalc=True)

                    # Перевірка периметру: Safe Zombie (2-й цикл) викликає execute_smart_rebalance_order БЕЗ allow_smart_maker!
                    orch._zombie_streaks["ETHUSDT"] = 1
                    ex.fetch_account_snapshot = AsyncMock(return_value=(1000.0, 0.0, {
                        "ETHUSDT": ExchangePositionDTO(symbol="ETHUSDT", contracts_qty=0.10, mark_price=2000.0),
                    }, True))
                    ex.fetch_all_open_orders_by_symbol = AsyncMock(return_value={"ETHUSDT": []})
                    await orch._run_post_rebalance_watchdog(
                        active_syms=("ETHUSDT",),
                        coin_targets_map={"ETHUSDT": 0.0, "LINKUSDT": 0.08},
                        coin_prices={"ETHUSDT": 2000.0, "LINKUSDT": 20.0},
                        phase_a_plans=[],
                        phase_b_plans=[],
                        executed_orders_summary=[],
                    )
            finally:
                object.__setattr__(settings, "SMART_MAKER_CHASE_ENABLED", orig_sm)
                object.__setattr__(settings, "SMART_MAKER_CONCURRENCY", orig_conc)
                object.__setattr__(settings, "USE_DEMO_TRADING", orig_demo)

            # 1) Конкурентність ніколи не перевищила SMART_MAKER_CONCURRENCY == 2
            self.assertLessEqual(max_in_flight, 2)

            # 2) Усі події END Фази 1 (ETH close, AVAX trim, SOL Flip Leg1 close — всі reduce_only=True, sm=True)
            # відбулися СТРОГО ДО першого START Фази 2 (SOL Flip Leg2 + LINK/NEAR/SUI — reduce_only=False)!
            phase1_end_indices = [
                idx for idx, ev in enumerate(call_events) if ev[0] == "END" and ev[2] is True and ev[3] is True
            ]
            phase2_start_indices = [
                idx for idx, ev in enumerate(call_events) if ev[0] == "START" and ev[2] is False and ev[3] is True
            ]
            self.assertEqual(len(phase1_end_indices), 3)   # ETH, AVAX, SOL Leg 1
            self.assertEqual(len(phase2_start_indices), 4)  # SOL Leg 2, LINK, NEAR, SUI
            self.assertLess(max(phase1_end_indices), min(phase2_start_indices))

            # 3) І NeutralityGuard, і Safe Zombie викликали execute_smart_rebalance_order із allow_smart_maker == False!
            non_sm_starts = [ev for ev in call_events if ev[0] == "START" and ev[2] is True and ev[3] is False]
            self.assertIn("ETHUSDT", [ev[1] for ev in non_sm_starts])

            # 4) Перевірка агрегації Implementation Shortfall у audit_report.py
            agg = aggregate_order_lifecycle_telemetry(tmp_dir / "lake")
            self.assertEqual(agg["lifecycle_filled_orders"], 7)
            self.assertAlmostEqual(agg["mean_maker_fill_ratio"], 1.0, places=4)
            self.assertAlmostEqual(agg["drift_abort_rate"], 0.0, places=4)
            # Пасивне покращення ціни -3.0 bps + 2.0 bps VIP0 мейкер комісія = -1.0 bps IS!
            self.assertAlmostEqual(agg["mean_implementation_shortfall_bps"], -1.0, places=2)


if __name__ == "__main__":
    unittest.main()
