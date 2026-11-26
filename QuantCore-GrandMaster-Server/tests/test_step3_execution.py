import sys
import os
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

server_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from app.domain.schemas import OrderExecutionDTO
from app.services.exchange_ccxt_service import ExchangeCcxtService


class TestStep3Execution(unittest.TestCase):

    def setUp(self):
        self.logger = MagicMock()
        self.db_service = MagicMock()
        self.exchange_service = ExchangeCcxtService(logger=self.logger, db_service=self.db_service)
        self.mock_ccxt = MagicMock()
        self.mock_ccxt.amount_to_precision = MagicMock(side_effect=lambda _s, q: str(round(float(q), 6)))
        self.mock_ccxt.price_to_precision = MagicMock(side_effect=lambda _s, p: str(round(float(p), 6)))
        self.exchange_service._exchange = self.mock_ccxt

    def test_sync_stop_closure_take_profit_note(self):
        """Перевірка правильної класифікації MFE_HARVESTER_TP при додатному PnL."""
        self.mock_ccxt.cancel_all_orders = MagicMock()
        # Mock trade with positive realizedPnl
        self.mock_ccxt.fetch_my_trades = MagicMock(return_value=[
            {
                "order": "123456",
                "amount": 0.5,
                "price": 68000.0,
                "side": "sell",
                "fee": {"cost": 0.15},
                "info": {"realizedPnl": "25.50"},
            }
        ])

        res = self.exchange_service._sync_exchange_stop_closure_sync("BTCUSDT")
        self.assertIsNotNone(res)
        tot_qty, avg_p, tot_pnl = res
        self.assertEqual(tot_pnl, 25.50)

        # Перевіряємо що в БД записано note='MFE_HARVESTER_TP'
        self.db_service.record_trade.assert_called_once()
        _, kwargs = self.db_service.record_trade.call_args
        self.assertEqual(kwargs.get("note"), "MFE_HARVESTER_TP")

    def test_sync_stop_closure_stop_loss_note(self):
        """Перевірка правильної класифікації STOP_LOSS_EXCHANGE при від'ємному PnL."""
        self.mock_ccxt.cancel_all_orders = MagicMock()
        self.mock_ccxt.fetch_my_trades = MagicMock(return_value=[
            {
                "order": "123457",
                "amount": 0.5,
                "price": 64000.0,
                "side": "sell",
                "fee": {"cost": 0.15},
                "info": {"realizedPnl": "-35.20"},
            }
        ])

        res = self.exchange_service._sync_exchange_stop_closure_sync("BTCUSDT")
        self.assertIsNotNone(res)
        tot_qty, avg_p, tot_pnl = res
        self.assertEqual(tot_pnl, -35.20)

        self.db_service.record_trade.assert_called_once()
        _, kwargs = self.db_service.record_trade.call_args
        self.assertEqual(kwargs.get("note"), "STOP_LOSS_EXCHANGE")

    def test_cancel_all_stink_bids(self):
        """Перевірка скасування тільки пасивних лімітних ордерів (stink bids), зберігаючи стопи."""
        self.mock_ccxt.fetch_open_orders = MagicMock(return_value=[
            {"id": "limit_1", "type": "limit"},
            {"id": "stop_1", "type": "stop_market"},
            {"id": "tp_1", "type": "take_profit_market"},
        ])
        self.mock_ccxt.cancel_order = MagicMock()

        cnt = self.exchange_service._cancel_all_stink_bids_sync(["BTCUSDT"])
        self.assertEqual(cnt, 1)
        self.mock_ccxt.cancel_order.assert_called_once_with("limit_1", "BTC/USDT:USDT")

    def test_phase1_config_sync_and_book_aware_sl_tp(self):
        """Перевірка синхронізації конфігурації (25 пар, 10x, 0.015) та Book-Aware SL/TP."""
        from app.core.config import settings
        from app.domain.schemas import CoinStateDTO
        from app.services.state_service import StateService
        from app.services.execution_service import MultiAssetExecutionOrchestrator

        self.assertEqual(len(settings.DEFAULT_SYMBOLS), 25)
        self.assertGreaterEqual(settings.EXCHANGE_LEVERAGE, 10)
        self.assertAlmostEqual(settings.CASH_ZONE_THRESHOLD, 0.015, places=4)

        async def _verify():
            st = StateService()
            st.coins["SOLUSDT"] = CoinStateDTO(
                symbol="SOLUSDT",
                enabled=True,
                current_pos_qty=2.0,
                entry_price=100.0,
                dominant_book="B1_STATARB",
                sl_atr_mult=8.0,
                tp_atr_mult=0.0,
            )
            ex = MagicMock()
            ex.safe_price = MagicMock(side_effect=lambda sym, p: round(p, 4))
            ex.place_or_update_stop_loss = AsyncMock(return_value=True)
            orch = MultiAssetExecutionOrchestrator(
                logger=MagicMock(),
                state_service=st,
                db_service=MagicMock(),
                exchange_service=ex,
                cartridge_service=MagicMock(),
                online_learner=MagicMock(),
                news_service=MagicMock(),
            )
            await orch._monitor_coin_breakeven("SOLUSDT", 102.0, 1.0)  # +2.0 ATR > 1.20
            self.assertFalse(st.coins["SOLUSDT"].is_breakeven)
            ex.place_or_update_stop_loss.assert_not_called()

            # Legacy empty dominant_book retains 1.20 ATR breakeven behavior
            st.coins["SOLUSDT"].dominant_book = ""
            await orch._monitor_coin_breakeven("SOLUSDT", 102.0, 1.0)
            self.assertTrue(st.coins["SOLUSDT"].is_breakeven)
            ex.place_or_update_stop_loss.assert_called_once()

        asyncio.run(_verify())

    def test_run_step_b1_skips_tp_vs_b3_places_tp(self):
        """E2E run_step: B1_STATARB ставить широкий 8.0 ATR SL без TP, а B3_SQUEEZE_SNIPER ставить 2.50 ATR SL і 2.60 ATR TP."""
        import pandas as pd
        from app.domain.schemas import CoinStateDTO, CoinTargetDTO, PortfolioTargetDTO, OrderExecutionDTO
        from app.services.state_service import StateService
        from app.services.execution_service import MultiAssetExecutionOrchestrator

        df_btc = pd.DataFrame({"timestamp": ["2026-11-01T00:00:00Z"] * 210, "close": [100000.0] * 210})
        df_sol = pd.DataFrame({"timestamp": ["2026-11-01T00:00:00Z"] * 210, "close": [100.0] * 210})

        st = StateService()
        st.coins["BTCUSDT"] = CoinStateDTO(symbol="BTCUSDT", enabled=True, current_pos_qty=0.0)
        st.coins["SOLUSDT"] = CoinStateDTO(symbol="SOLUSDT", enabled=True, current_pos_qty=0.0)
        st.max_portfolio_lev = 3.0

        dto = PortfolioTargetDTO(
            cartridge_name="test_cart",
            architecture="5Book",
            candle_timestamp="2026-11-01T00:00:00Z",
            market_breadth=0.5,
            news_sentiment=0.0,
            total_gross_leverage=1.0,
            net_leverage=0.0,
            targets={
                "BTCUSDT": CoinTargetDTO(
                    symbol="BTCUSDT", desired_weight=0.5, raw_model_pos=0.5, phase=1,
                    alpha_score=1.0, signal_macro=0.2, signal_ml=0.8, ker_purity=0.55,
                    zscore_96=0.0, rs_vs_btc=0.0, current_price=100000.0, atr_14=500.0,
                    dominant_book="B1_STATARB", sl_atr_mult=8.0, tp_atr_mult=0.0,
                ),
                "SOLUSDT": CoinTargetDTO(
                    symbol="SOLUSDT", desired_weight=-0.5, raw_model_pos=-0.5, phase=-1,
                    alpha_score=-1.2, signal_macro=0.2, signal_ml=-0.9, ker_purity=0.85,
                    zscore_96=0.0, rs_vs_btc=0.0, current_price=100.0, atr_14=2.0,
                    dominant_book="B3_SQUEEZE_SNIPER", sl_atr_mult=2.50, tp_atr_mult=2.60,
                ),
            },
            extra_telemetry={},
        )

        cart = MagicMock()
        cart.supported_symbols = ["BTCUSDT", "SOLUSDT"]
        cart.compute_portfolio_targets = MagicMock(return_value=dto)
        cart_srv = MagicMock()
        cart_srv.cartridge = cart
        cart_srv.active_name = "test_cart"

        async def _mock_exec(symbol, delta_qty, mark_price, **kwargs):
            return OrderExecutionDTO(
                order_id=f"ord_{symbol}", symbol=symbol,
                side="BUY" if delta_qty > 0 else "SELL",
                executed_qty=abs(delta_qty), avg_price=mark_price,
                fee_usdt=0.1, realized_pnl_est=0.0, note="test",
            )

        ex = MagicMock()
        ex.safe_price = MagicMock(side_effect=lambda s, p: round(p, 4))
        ex.safe_amount = MagicMock(side_effect=lambda s, q: round(q, 4))
        ex.fetch_delta_candles = AsyncMock(side_effect=lambda s, limit=None: df_btc if s == "BTCUSDT" else df_sol)
        ex.fetch_account_snapshot = AsyncMock(return_value=(1000.0, 0.0, {}, True))
        ex.fetch_funding_rates = AsyncMock(return_value={"BTCUSDT": 0.0, "SOLUSDT": 0.0})
        ex.cancel_symbol_orders = AsyncMock()
        ex.cancel_all_stink_bids = AsyncMock()
        ex.place_passive_stink_bid = AsyncMock(return_value="st1")
        ex.execute_smart_rebalance_order = AsyncMock(side_effect=_mock_exec)
        ex.place_or_update_stop_loss = AsyncMock(return_value=True)
        ex.place_or_update_take_profit = AsyncMock(return_value=True)

        news = MagicMock()
        news.geo_shock_prob = 0.0
        news.fetch_market_intelligence = AsyncMock(return_value={"macro_sentiment": 0.0, "is_geo_shock": False, "coin_bias": {}})
        learner = MagicMock()
        learner.get_all_learning_states = MagicMock(return_value={})
        learner.record_step_and_adapt = MagicMock(return_value=1.0)
        db_mock = MagicMock()
        db_mock.get_daily_realized_pnl = MagicMock(return_value=0.0)

        orch = MultiAssetExecutionOrchestrator(
            logger=MagicMock(),
            state_service=st,
            db_service=db_mock,
            exchange_service=ex,
            cartridge_service=cart_srv,
            online_learner=learner,
            news_service=news,
        )
        with patch.object(StateService, "save_snapshot", return_value=None):
            asyncio.run(orch.run_step(force_recalc=True))

        sl_calls = {c.args[0]: c.args[2] for c in ex.place_or_update_stop_loss.call_args_list}
        tp_calls = {c.args[0]: c.args[2] for c in ex.place_or_update_take_profit.call_args_list}
        self.assertAlmostEqual(sl_calls["BTCUSDT"], 100000.0 - 8.0 * 500.0, places=2)
        self.assertNotIn("BTCUSDT", tp_calls)
        self.assertAlmostEqual(sl_calls["SOLUSDT"], 100.0 + 2.50 * 2.0, places=2)
        self.assertAlmostEqual(tp_calls["SOLUSDT"], 100.0 - 2.60 * 2.0, places=2)

    def test_maker_first_skips_taker_fallback_on_non_urgent_b1(self):
        """Maker-First (postOnly) не виконує Taker market fallback при нетерміновому вході Book 1."""
        self.mock_ccxt.fetch_order_book = MagicMock(return_value={
            "bids": [[99.9, 100.0]], "asks": [[100.0, 100.0]],
        })
        self.mock_ccxt.create_order = MagicMock(side_effect=Exception("PostOnly would cross"))
        self.mock_ccxt.create_market_order = MagicMock()

        res = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=1.0, mark_price=99.95,
            realized_pnl_est=0.0, note="B1 maker", reduce_only=False, maker_first=True,
        )
        self.assertIsNone(res)
        self.mock_ccxt.create_market_order.assert_not_called()

        # When reduce_only=True (urgent close), fallback to Taker market IS allowed even if maker_first=True
        self.mock_ccxt.create_market_order.return_value = {
            "id": "m1", "filled": 1.0, "average": 100.0, "fee": {"cost": 0.05},
        }
        res_close = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=-1.0, mark_price=99.95,
            realized_pnl_est=5.0, note="B1 close", reduce_only=True, maker_first=True,
        )
        self.assertIsNotNone(res_close)
        self.mock_ccxt.create_market_order.assert_called_once()

    def test_v6_risk_guard_hard_caps_and_signal_isolation(self):
        """Step 4: RiskGuard enforces <=2.25x gross, >5% daily DD, >15% total DD, stale data & news/online isolation."""
        import pandas as pd
        from app.domain.schemas import CoinTargetDTO, PortfolioTargetDTO
        from app.services.risk_guard_service import RiskGuardService
        from app.services.state_service import StateService

        st = StateService()
        db_m = MagicMock()
        db_m.get_daily_realized_pnl = MagicMock(return_value=0.0)
        ex_m = MagicMock()
        orch_m = MagicMock()
        orch_m.emergency_close_all_positions = AsyncMock(return_value="closed")

        rg = RiskGuardService(logger=MagicMock(), state_service=st, db_service=db_m, exchange_service=ex_m)
        rg.bind_orchestrator(orch_m)

        # 1. Hard Gross Leverage Cap <= 2.25x
        dto = PortfolioTargetDTO(
            cartridge_name="v5_multi_sleeve", architecture="QuantCore_V5_AllRegime_58Assets",
            candle_timestamp="2026-11-21T00:00:00Z", market_breadth=0.5, news_sentiment=0.0,
            total_gross_leverage=3.0, net_leverage=0.0,
            targets={
                "ETHUSDT": CoinTargetDTO(
                    symbol="ETHUSDT", desired_weight=1.5, raw_model_pos=1.5, phase=2,
                    alpha_score=1.0, signal_macro=0.0, signal_ml=0.0, ker_purity=0.0,
                    zscore_96=0.0, rs_vs_btc=0.0, current_price=3000.0, atr_14=50.0,
                ),
                "SOLUSDT": CoinTargetDTO(
                    symbol="SOLUSDT", desired_weight=-1.5, raw_model_pos=-1.5, phase=-1,
                    alpha_score=-1.0, signal_macro=0.0, signal_ml=0.0, ker_purity=0.0,
                    zscore_96=0.0, rs_vs_btc=0.0, current_price=150.0, atr_14=3.0,
                ),
            },
        )
        capped = rg.enforce_gross_leverage_cap(dto)
        self.assertAlmostEqual(capped.total_gross_leverage, 2.25, places=6)
        self.assertAlmostEqual(abs(capped.targets["ETHUSDT"].desired_weight) + abs(capped.targets["SOLUSDT"].desired_weight), 2.25, places=6)

        # 2. Stale Market Data Guard
        df_stale = pd.DataFrame({"open_ms": [1_700_000_000_000], "close": [90000.0]})
        is_st, rsn = rg.check_stale_market_data({"BTCUSDT": df_stale}, now_ts=1_700_000_000.0 + 14400.0)
        self.assertTrue(is_st)
        self.assertIn("stale_btcusdt", rsn)
        is_ok, _ = rg.check_stale_market_data({"BTCUSDT": df_stale}, now_ts=1_700_000_000.0 + 600.0)
        self.assertFalse(is_ok)

        # 3. Daily Drawdown > 5% Breaker & Total Drawdown > 15% Hard Stop
        with patch.object(StateService, "save_snapshot", return_value=None):
            tripped0, _ = asyncio.run(rg.check_circuit_breaker(500.0))
            self.assertFalse(tripped0)
            # -5.4% daily loss -> trips daily breaker (pause_until is set)
            tripped_d, _ = asyncio.run(rg.check_circuit_breaker(473.0))
            self.assertTrue(tripped_d)
            self.assertTrue(st.is_paused)
            self.assertIsNotNone(st.pause_until)

            # Unpause, new day baseline 410, peak is still 500 -> equity 395 is -3.66% daily (<5%) BUT -21.0% from peak (>20%)!
            st.is_paused = False
            st.pause_until = None
            st.daily_starting_equity = 410.0
            st.peak_equity = 500.0
            tripped_tot, _ = asyncio.run(rg.check_circuit_breaker(395.0))
            self.assertTrue(tripped_tot)
            self.assertTrue(st.is_paused)
            self.assertIsNone(st.pause_until)  # Hard manual-review stop (no auto-resume!)

    def test_minus_2022_reduce_only_never_reopens_reverse_position(self):
        """Критичний тест безпеки V6.1: помилка -2022 на reduceOnly НІКОЛИ не відкриває голу зустрічну позицію!"""
        self.mock_ccxt.fetch_order_book = MagicMock(return_value={
            "bids": [[100.0, 50.0]], "asks": [[100.05, 50.0]],
        })
        self.mock_ccxt.create_market_order = MagicMock(
            side_effect=Exception("binance {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}")
        )
        self.mock_ccxt.create_order = MagicMock()

        res = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=2.0, mark_price=100.0,
            realized_pnl_est=0.0, note="Close short after SL already fired",
            reduce_only=True, maker_first=False, taker_fallback=True,
        )
        self.assertIsNone(res)
        # create_market_order викликано РІВНО 1 раз із reduceOnly=True (жодного повторного виклику без reduceOnly!)
        self.assertEqual(self.mock_ccxt.create_market_order.call_count, 1)
        _, kwargs = self.mock_ccxt.create_market_order.call_args
        self.assertTrue(kwargs["params"].get("reduceOnly"))
        self.assertIn("newClientOrderId", kwargs["params"])
        self.assertEqual(self.exchange_service.get_last_order_diag("SOLUSDT").get("order_status"), "ALREADY_CLOSED_2022")

    def test_protected_ioc_entry_and_client_order_id_idempotency(self):
        """V6.1 вхід використовує Protected Limit IOC (BBO ± max_slip) та детермінований newClientOrderId."""
        self.mock_ccxt.fetch_order_book = MagicMock(return_value={
            "bids": [[200.0, 50.0]], "asks": [[200.10, 50.0]],
        })
        self.mock_ccxt.create_order = MagicMock(return_value={
            "id": "ioc_999", "type": "limit", "filled": 1.0, "average": 200.12, "fee": {"cost": 0.10},
        })
        self.mock_ccxt.create_market_order = MagicMock()

        res = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=1.0, mark_price=200.05,
            realized_pnl_est=0.0, note="V6.1 IOC entry",
            reduce_only=False, maker_first=False, taker_fallback=True,
        )
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.executed_qty, 1.0)
        self.mock_ccxt.create_market_order.assert_not_called()
        self.mock_ccxt.create_order.assert_called_once()
        _, c_kwargs = self.mock_ccxt.create_order.call_args
        self.assertEqual(c_kwargs.get("type"), "limit")
        self.assertEqual(c_kwargs["params"].get("timeInForce"), "IOC")
        self.assertTrue(str(c_kwargs["params"].get("newClientOrderId", "")).startswith("qc6_SOLUSDT_BO_"))
        # Захисна ціна IOC не перевищує best_ask * (1 + 0.0025)
        self.assertLessEqual(float(c_kwargs.get("price")), 200.10 * 1.0026)

    def test_conditional_trigger_orphan_sl_cleanup_and_delisting_guard(self):
        """Прибирання умовних Algo/Trigger SL (params={'trigger': True}) та детектор делістингу deliveryDate."""
        def _mock_open_orders(sym, params=None):
            if params and params.get("trigger"):
                return [{"id": "algo_sl_77", "type": "stop_market"}]
            return [{"id": "reg_lim_11", "type": "limit"}]

        self.mock_ccxt.fetch_open_orders = MagicMock(side_effect=_mock_open_orders)
        self.mock_ccxt.cancel_order = MagicMock()

        cleaned = self.exchange_service._cleanup_orphan_orders_sync(
            {"SOLUSDT": 0.0, "ETHUSDT": 0.5}, candidate_symbols=("SOLUSDT", "ETHUSDT")
        )
        self.assertEqual(cleaned, 2)
        cancel_calls = self.mock_ccxt.cancel_order.call_args_list
        self.assertEqual(len(cancel_calls), 2)
        self.assertEqual(cancel_calls[1].kwargs.get("params"), {"trigger": True})

        # Перевірка детектора делістингу deliveryDate
        now_ms = 1_760_000_000_000
        self.mock_ccxt.markets = {
            "BTC/USDT:USDT": {"active": True, "info": {"status": "TRADING", "deliveryDate": "4133404800000"}},
            "OMG/USDT:USDT": {"active": True, "info": {"status": "TRADING", "deliveryDate": str(now_ms + 24 * 3_600_000)}},
        }
        delist = self.exchange_service.get_delisting_symbols(("BTCUSDT", "OMGUSDT"), buffer_hours=72.0, now_ms=now_ms)
        self.assertNotIn("BTCUSDT", delist)
        self.assertIn("OMGUSDT", delist)

    def test_v6_fail_closed_and_pre_spread_neutrality_scaling(self):
        """Fail-Closed блокує сліпу деградацію у V2 без OI, а Pre-Spread Filter симетрично масштабує протилежний бік."""
        import numpy as np
        import pandas as pd
        try:
            from app.cartridges.v2_multi_sleeve_cartridge import V2MultiSleeveCartridge
        except ImportError:
            V2MultiSleeveCartridge = None
        from app.domain.schemas import CoinStateDTO, CoinTargetDTO, PortfolioTargetDTO
        from app.services.state_service import StateService
        from app.services.execution_service import MultiAssetExecutionOrchestrator

        # 1. Fail-Closed на V6 без колонки oi_usd (якщо пропрієтарний картридж встановлено локально)
        ts = np.arange(400, dtype=np.int64) * 3_600_000 + 1_700_000_000_000
        candles_no_oi = {
            s: pd.DataFrame({
                "open_ms": ts, "timestamp": pd.to_datetime(ts, unit="ms", utc=True),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                "volume": 1000.0, "quote_volume": 100000.0, "funding_rate": 0.0001,
            })
            for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
        }
        if V2MultiSleeveCartridge is not None:
            coins = {s: CoinStateDTO(symbol=s, current_pos_qty=1.0 if s == "SOLUSDT" else 0.0) for s in candles_no_oi}
            cart_v6 = V2MultiSleeveCartridge(symbols=tuple(candles_no_oi), engine_ver="v6")
            dto_fc = cart_v6.compute_portfolio_targets(
                candles_no_oi, coins, {}, 2.0, "PORTFOLIO_SYNERGY", 0.0, {}, False, {}, account_equity=500.0
            )
            self.assertTrue(dto_fc.extra_telemetry.get("fail_closed"))
            self.assertEqual(len(dto_fc.targets), 0)  # Жодного примусового закриття або сліпого V2 ребалансу!

        # 2. Pre-Spread Filter: якщо шорт-нога має широкий спред (120 bps > 55 bps), лонг-нога симетрично скасовується/стискається
        st = StateService()
        for s in ("BTCUSDT", "SOLUSDT", "XRPUSDT"):
            st.coins[s] = CoinStateDTO(symbol=s, enabled=True, current_pos_qty=0.0)
        dto_sp = PortfolioTargetDTO(
            cartridge_name="v6_multi_sleeve", architecture="QuantCore_V6_1_Institutional_58Assets",
            candle_timestamp="2026-11-21T00:00:00Z", market_breadth=0.5, news_sentiment=0.0,
            total_gross_leverage=0.8, net_leverage=0.0,
            targets={
                "SOLUSDT": CoinTargetDTO(
                    symbol="SOLUSDT", desired_weight=0.40, raw_model_pos=0.40, phase=2,
                    alpha_score=1.0, signal_macro=0.0, signal_ml=0.0, ker_purity=0.0,
                    zscore_96=0.0, rs_vs_btc=0.0, current_price=100.0, atr_14=3.0,
                    dominant_book="V2_MOMENTUM", sl_atr_mult=8.0, tp_atr_mult=0.0,
                ),
                "XRPUSDT": CoinTargetDTO(
                    symbol="XRPUSDT", desired_weight=-0.40, raw_model_pos=-0.40, phase=-1,
                    alpha_score=-1.0, signal_macro=0.0, signal_ml=0.0, ker_purity=0.0,
                    zscore_96=0.0, rs_vs_btc=0.0, current_price=1.0, atr_14=0.03,
                    dominant_book="V2_MOMENTUM", sl_atr_mult=4.8, tp_atr_mult=0.0,
                ),
            },
            extra_telemetry={"any_rebalanced": True},
        )
        cart_m = MagicMock()
        cart_m.supported_symbols = ("BTCUSDT", "SOLUSDT", "XRPUSDT")
        cart_m.compute_portfolio_targets = MagicMock(return_value=dto_sp)
        cart_srv = MagicMock(cartridge=cart_m, active_name="v6_multi_sleeve")

        ex = MagicMock()
        ex.safe_price = MagicMock(side_effect=lambda s, p: round(p, 4))
        ex.safe_amount = MagicMock(side_effect=lambda s, q: round(q, 4))
        ex.fetch_delta_candles = AsyncMock(side_effect=lambda s, limit=None: candles_no_oi[s])
        ex.fetch_account_snapshot = AsyncMock(return_value=(500.0, 0.0, {}, True))
        ex.fetch_funding_rates = AsyncMock(return_value={"SOLUSDT": 0.0, "XRPUSDT": 0.0})
        ex.fetch_market_microstructure = AsyncMock(return_value={
            "SOLUSDT": {"spread_bps": 4.0},
            "XRPUSDT": {"spread_bps": 120.0},  # > 55 bps -> відсікається ДО відправки!
        })
        ex.execute_smart_rebalance_order = AsyncMock()
        ex.cleanup_orphan_orders = AsyncMock(return_value=0)
        db_m = MagicMock()
        db_m.get_daily_realized_pnl = MagicMock(return_value=0.0)
        news_m = MagicMock(geo_shock_prob=0.0)
        orch = MultiAssetExecutionOrchestrator(
            logger=MagicMock(), state_service=st, db_service=db_m, exchange_service=ex,
            cartridge_service=cart_srv, online_learner=MagicMock(), news_service=news_m,
        )
        with patch.object(StateService, "save_snapshot", return_value=None):
            asyncio.run(orch.run_step(force_recalc=True))
        # Оскільки єдиний шорт XRPUSDT відсіяно спредом 120 bps, лонг SOLUSDT теж симетрично стиснуто до 0 -> 0 голих ордерів!
        ex.execute_smart_rebalance_order.assert_not_called()

    def test_rbac_viewer_read_only_vs_admin_and_rate_limit(self):
        """RBAC: viewer читає телеметрію, але отримує 403 на всі керуючі/завантажувальні роути."""
        import tempfile
        from fastapi.testclient import TestClient
        from app.core.config import settings
        from app.core.security import reset_login_failures
        from main import app

        orig_view = settings.DASHBOARD_VIEW_PASSWORD
        orig_pw = settings.DASHBOARD_PASSWORD
        orig_key_file = settings.DASHBOARD_ADMIN_KEY_FILE
        client = TestClient(app)
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
                tf.write("admin_file_secret_999\n")
                key_path = tf.name
            object.__setattr__(settings, "DASHBOARD_ADMIN_KEY_FILE", key_path)
            object.__setattr__(settings, "DASHBOARD_PASSWORD", "fallback_admin")
            object.__setattr__(settings, "DASHBOARD_VIEW_PASSWORD", "view_only_123")
            reset_login_failures("testclient")

            # 1. Логін як viewer
            r_v = client.post("/api/v1/auth/login", json={"password": "view_only_123"})
            self.assertEqual(r_v.status_code, 200)
            self.assertEqual(r_v.json().get("role"), "viewer")
            self.assertNotIn("token", r_v.json())

            # Перегляд дозволено (200) + роль viewer у сесії та /state
            self.assertEqual(client.get("/api/v1/auth/session").json().get("role"), "viewer")
            st_resp = client.get("/api/v1/state")
            self.assertEqual(st_resp.status_code, 200)
            self.assertEqual(st_resp.json().get("auth_role"), "viewer")

            # Будь-які керуючі/небезпечні дії для viewer блокуються з 403
            self.assertEqual(client.post("/api/v1/system/wakeup").status_code, 403)
            self.assertEqual(client.post("/api/v1/control/pause", json={"paused": True}).status_code, 403)
            self.assertEqual(client.post("/api/v1/cartridge/upload", content=b"123").status_code, 403)
            self.assertEqual(client.get("/api/v1/v2/export").status_code, 403)

            # 2. Логін як admin через окремий файл ключа (.admin_key)
            r_a = client.post("/api/v1/auth/login", json={"password": "admin_file_secret_999"})
            self.assertEqual(r_a.status_code, 200)
            self.assertEqual(r_a.json().get("role"), "admin")
            self.assertEqual(client.post("/api/v1/system/wakeup").status_code, 200)

            # 3. Rate limit (5 невдач -> 429)
            client.post("/api/v1/auth/logout")
            reset_login_failures("testclient")
            for _ in range(5):
                self.assertEqual(client.post("/api/v1/auth/login", json={"password": "bad"}).status_code, 401)
            self.assertEqual(client.post("/api/v1/auth/login", json={"password": "bad"}).status_code, 429)
        finally:
            reset_login_failures("testclient")
            object.__setattr__(settings, "DASHBOARD_VIEW_PASSWORD", orig_view)
            object.__setattr__(settings, "DASHBOARD_PASSWORD", orig_pw)
            object.__setattr__(settings, "DASHBOARD_ADMIN_KEY_FILE", orig_key_file)
            if "key_path" in locals() and os.path.exists(key_path):
                os.remove(key_path)

    def test_stop_market_uses_close_position_without_qty_or_reduce_only(self):
        """100% позиційний STOP_MARKET використовує closePosition=True без amount/quantity і без reduceOnly (-1106)."""
        self.mock_ccxt.fetch_open_orders = MagicMock(return_value=[])
        self.mock_ccxt.create_order = MagicMock(return_value={"id": "sl_cp_1"})
        ok, reason = self.exchange_service._place_stop_loss_ex_sync("SOLUSDT", 5.0, 92.5)
        self.assertTrue(ok)
        self.assertEqual(reason, "OK")
        _, kwargs = self.mock_ccxt.create_order.call_args
        self.assertIsNone(kwargs.get("amount"))
        self.assertEqual(kwargs["type"], "STOP_MARKET")
        self.assertTrue(kwargs["params"].get("closePosition"))
        self.assertNotIn("reduceOnly", kwargs["params"])

    def test_2022_case1_position_already_closed_cleans_orders(self):
        """Кейс 1 (-2022): REST підтверджує live_qty == 0 -> чистий вихід + очищення ордерів."""
        self.mock_ccxt.fetch_order_book = MagicMock(return_value={
            "bids": [[100.0, 50.0]], "asks": [[100.05, 50.0]],
        })
        self.mock_ccxt.create_market_order = MagicMock(
            side_effect=Exception("binance {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}")
        )
        self.mock_ccxt.fetch_positions = MagicMock(return_value=[])
        self.mock_ccxt.fetch_open_orders = MagicMock(side_effect=lambda sym, params=None: (
            [{"id": "orphan_sl", "type": "stop_market", "stopPrice": 90.0}] if (params and params.get("trigger")) else []
        ))
        self.mock_ccxt.cancel_all_orders = MagicMock()
        self.mock_ccxt.cancel_order = MagicMock()

        res = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=-2.0, mark_price=100.0,
            realized_pnl_est=0.0, note="Close case 1",
            reduce_only=True, maker_first=False, taker_fallback=True,
        )
        self.assertIsNone(res)
        self.assertEqual(self.exchange_service.get_last_order_diag("SOLUSDT").get("order_status"), "ALREADY_CLOSED_2022")
        self.assertEqual(self.mock_ccxt.create_market_order.call_count, 1)
        self.mock_ccxt.cancel_all_orders.assert_called_once()
        self.mock_ccxt.cancel_order.assert_called_once_with("orphan_sl", "SOL/USDT:USDT", params={"trigger": True})

    def test_2022_case2_blocked_by_stop_market_full_close_retries(self):
        """Кейс 2 (-2022): позиція відкрита (2.0), блокує STOP_MARKET -> cancel orders -> повне закриття reduceOnly."""
        self.mock_ccxt.fetch_order_book = MagicMock(return_value={
            "bids": [[100.0, 50.0]], "asks": [[100.05, 50.0]],
        })
        # postOnly maker падає з -2022 (квоту блокує старий STOP_MARKET), повторний postOnly теж відхиляється -> MARKET fallback успішний
        self.mock_ccxt.create_order = MagicMock(side_effect=[
            Exception("binance {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}"),
            Exception("PostOnly would immediately match"),
        ])
        self.mock_ccxt.fetch_positions = MagicMock(return_value=[
            {"symbol": "SOL/USDT:USDT", "contracts": 2.0, "side": "long"}
        ])
        self.mock_ccxt.fetch_open_orders = MagicMock(side_effect=lambda sym, params=None: (
            [{"id": "blk_sl_1", "type": "stop_market", "stopPrice": 91.0}] if (params and params.get("trigger")) else []
        ))
        self.mock_ccxt.cancel_all_orders = MagicMock()
        self.mock_ccxt.cancel_order = MagicMock()
        self.mock_ccxt.create_market_order = MagicMock(return_value={
            "id": "mkt_close_2", "filled": 2.0, "average": 100.0, "fee": {"cost": 0.1},
        })

        res = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=-2.0, mark_price=100.0,
            realized_pnl_est=5.0, note="Full close case 2",
            reduce_only=True, maker_first=True, taker_fallback=False,
        )
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.executed_qty, 2.0)
        self.mock_ccxt.cancel_order.assert_called_once_with("blk_sl_1", "SOL/USDT:USDT", params={"trigger": True})
        _, m_kwargs = self.mock_ccxt.create_market_order.call_args
        self.assertTrue(m_kwargs["params"].get("reduceOnly"))
        self.assertEqual(self.exchange_service.get_last_order_diag("SOLUSDT").get("order_status"), "FILLED_2022_RETRY")

    def test_2022_case3_partial_trim_cancels_sl_and_rearms_on_remainder(self):
        """Кейс 3 (-2022): частковий trim (4 з 10), блокує STOP_MARKET -> cancel -> trim -> перевиставлення SL на 6."""
        self.mock_ccxt.fetch_order_book = MagicMock(return_value={
            "bids": [[100.0, 200.0]], "asks": [[100.05, 200.0]],
        })
        self.mock_ccxt.fetch_positions = MagicMock(return_value=[
            {"symbol": "SOL/USDT:USDT", "contracts": 10.0, "side": "long"}
        ])
        open_calls = {"n": 0}
        def _open_orders_case3(sym, params=None):
            open_calls["n"] += 1
            if params and params.get("trigger") and open_calls["n"] <= 4:
                return [{"id": "blk_sl_3", "type": "stop_market", "stopPrice": 88.0}]
            return []
        self.mock_ccxt.fetch_open_orders = MagicMock(side_effect=_open_orders_case3)
        self.mock_ccxt.cancel_all_orders = MagicMock()
        self.mock_ccxt.cancel_order = MagicMock()
        self.mock_ccxt.create_market_order = MagicMock(side_effect=[
            Exception("binance {'code': -2022, 'msg': 'ReduceOnly Order is rejected.'}"),
            {"id": "mkt_trim_3", "filled": 4.0, "average": 100.0, "fee": {"cost": 0.2}},
        ])
        self.mock_ccxt.create_order = MagicMock(return_value={"id": "sl_rearmed_6"})

        res = self.exchange_service._execute_smart_order_sync(
            symbol="SOLUSDT", delta_qty=-4.0, mark_price=100.0,
            realized_pnl_est=2.0, note="Partial trim case 3",
            reduce_only=True, maker_first=False, taker_fallback=True,
            active_sl_price=88.0,
        )
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res.executed_qty, 4.0)
        self.assertEqual(self.mock_ccxt.create_market_order.call_count, 2)
        self.mock_ccxt.cancel_order.assert_called_once_with("blk_sl_3", "SOL/USDT:USDT", params={"trigger": True})
        # Перевірка перевиставлення STOP_MARKET у finally на залишок (6.0 != 0) за 88.0 із closePosition=True
        self.mock_ccxt.create_order.assert_called_once()
        _, sl_kw = self.mock_ccxt.create_order.call_args
        self.assertEqual(sl_kw["type"], "STOP_MARKET")
        self.assertEqual(sl_kw["side"], "sell")
        self.assertIsNone(sl_kw["amount"])
        self.assertAlmostEqual(float(sl_kw["params"]["stopPrice"]), 88.0)
        self.assertTrue(sl_kw["params"].get("closePosition"))
        self.assertTrue(self.exchange_service.get_last_order_diag("SOLUSDT").get("sl_rearmed_after_2022"))

    def test_watchdog_orphan_zombie_and_naked_sl_remediation(self):
        """Post-Rebalance Watchdog: чистить ордери-сироти, закриває zombie (target=0), ставить відсутній STOP_MARKET."""
        from app.domain.schemas import CoinStateDTO, ExchangePositionDTO, OrderExecutionDTO
        from app.services.state_service import StateService
        from app.services.execution_service import MultiAssetExecutionOrchestrator

        st = StateService()
        st.coins["BTCUSDT"] = CoinStateDTO(symbol="BTCUSDT", enabled=True, current_pos_qty=0.0)
        st.coins["ETHUSDT"] = CoinStateDTO(symbol="ETHUSDT", enabled=True, current_pos_qty=0.0)
        st.coins["SOLUSDT"] = CoinStateDTO(symbol="SOLUSDT", enabled=True, current_pos_qty=5.0, active_sl_price=90.0)

        ex = MagicMock()
        ex.fetch_account_snapshot = AsyncMock(return_value=(
            500.0, 0.0,
            {
                "BTCUSDT": ExchangePositionDTO(symbol="BTCUSDT", contracts_qty=0.0),
                "ETHUSDT": ExchangePositionDTO(symbol="ETHUSDT", contracts_qty=2.0, mark_price=3000.0),
                "SOLUSDT": ExchangePositionDTO(symbol="SOLUSDT", contracts_qty=5.0, mark_price=100.0),
            },
            True,
        ))
        ex.fetch_all_open_orders_by_symbol = AsyncMock(return_value={
            "BTCUSDT": [{"id": "orphan_1", "type": "limit"}],
            "ETHUSDT": [],
            "SOLUSDT": [],  # Немає STOP_MARKET -> Naked Position!
        })
        ex.cancel_symbol_orders = AsyncMock(return_value=True)
        ex.execute_smart_rebalance_order = AsyncMock(return_value=OrderExecutionDTO(
            symbol="ETHUSDT", side="SELL", executed_qty=2.0, avg_price=3000.0, fee_usdt=3.0,
        ))
        ex.place_or_update_stop_loss_ex = AsyncMock(return_value=(True, "OK"))

        tg = MagicMock()
        tg.send_alert = AsyncMock()
        orch = MultiAssetExecutionOrchestrator(
            logger=MagicMock(), state_service=st, db_service=MagicMock(),
            exchange_service=ex, cartridge_service=MagicMock(),
            online_learner=MagicMock(), news_service=MagicMock(),
        )
        orch._tg_sender = tg

        # 1-й здоровий цикл: чистить ордер-сироту по BTCUSDT, ставить Naked SL по SOLUSDT, а по ETHUSDT (Zombie 1/2) ЛИШЕ попереджає!
        asyncio.run(orch._run_post_rebalance_watchdog(
            active_syms=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            coin_targets_map={"BTCUSDT": 0.0, "ETHUSDT": 0.0, "SOLUSDT": 0.25},
            coin_prices={"BTCUSDT": 90000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0},
            phase_a_plans=[],
            phase_b_plans=[],
            executed_orders_summary=[],
        ))

        cancel_syms_1 = [c.args[0] for c in ex.cancel_symbol_orders.call_args_list]
        self.assertIn("BTCUSDT", cancel_syms_1)
        self.assertNotIn("ETHUSDT", cancel_syms_1)
        ex.execute_smart_rebalance_order.assert_not_awaited()
        ex.place_or_update_stop_loss_ex.assert_awaited_once_with("SOLUSDT", 5.0, 90.0)
        tg.send_alert.assert_awaited_once()

        # 2-й здоровий цикл: SOLUSDT вже має Binance CONDITIONAL STOP_MARKET (type='market', info.orderType='STOP_MARKET'),
        # а ETHUSDT (Zombie 2/2) тепер примусово закривається MARKET reduceOnly!
        ex.fetch_all_open_orders_by_symbol = AsyncMock(return_value={
            "BTCUSDT": [],
            "ETHUSDT": [],
            "SOLUSDT": [{
                "id": "algo_sl_1",
                "type": "market",
                "info": {"algoType": "CONDITIONAL", "orderType": "STOP_MARKET", "triggerPrice": "90.0"},
            }],
        })
        ex.place_or_update_stop_loss_ex.reset_mock()

        asyncio.run(orch._run_post_rebalance_watchdog(
            active_syms=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            coin_targets_map={"BTCUSDT": 0.0, "ETHUSDT": 0.0, "SOLUSDT": 0.25},
            coin_prices={"BTCUSDT": 90000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0},
            phase_a_plans=[],
            phase_b_plans=[],
            executed_orders_summary=[],
        ))

        cancel_syms = [c.args[0] for c in ex.cancel_symbol_orders.call_args_list]
        self.assertIn("ETHUSDT", cancel_syms)
        ex.execute_smart_rebalance_order.assert_awaited_once()
        _, z_kw = ex.execute_smart_rebalance_order.call_args
        self.assertEqual(z_kw["symbol"], "ETHUSDT")
        self.assertAlmostEqual(z_kw["delta_qty"], -2.0)
        self.assertTrue(z_kw["reduce_only"])
        # SOLUSDT вже мав CONDITIONAL STOP_MARKET -> повторне перевиставлення НЕ викликалось!
        ex.place_or_update_stop_loss_ex.assert_not_awaited()

    def test_watchdog_never_closes_positions_on_fail_closed_or_empty_targets(self):
        """Safe Zombie Guard: НІКОЛИ не закриває відкриті позиції при fail_closed=True або порожній книзі таргетів."""
        from app.domain.schemas import CoinStateDTO, ExchangePositionDTO
        from app.services.state_service import StateService
        from app.services.execution_service import MultiAssetExecutionOrchestrator

        st = StateService()
        st.coins["ETHUSDT"] = CoinStateDTO(symbol="ETHUSDT", enabled=True, current_pos_qty=2.0, active_sl_price=2800.0)

        ex = MagicMock()
        ex.fetch_account_snapshot = AsyncMock(return_value=(
            500.0, 0.0,
            {"ETHUSDT": ExchangePositionDTO(symbol="ETHUSDT", contracts_qty=2.0, mark_price=3000.0)},
            True,
        ))
        ex.fetch_all_open_orders_by_symbol = AsyncMock(return_value={
            "ETHUSDT": [{"id": "sl_eth", "type": "market", "info": {"algoType": "CONDITIONAL", "orderType": "STOP_MARKET"}}],
        })
        ex.execute_smart_rebalance_order = AsyncMock()

        orch = MultiAssetExecutionOrchestrator(
            logger=MagicMock(), state_service=st, db_service=MagicMock(),
            exchange_service=ex, cartridge_service=MagicMock(),
            online_learner=MagicMock(), news_service=MagicMock(),
        )
        # Навіть 3 виклики поспіль при fail_closed=True або порожніх таргетах НЕ чіпають позицію!
        for _ in range(3):
            asyncio.run(orch._run_post_rebalance_watchdog(
                active_syms=("ETHUSDT",),
                coin_targets_map={"ETHUSDT": 0.0},
                coin_prices={"ETHUSDT": 3000.0},
                phase_a_plans=[],
                phase_b_plans=[],
                executed_orders_summary=[],
                fail_closed=True,
            ))
            asyncio.run(orch._run_post_rebalance_watchdog(
                active_syms=("ETHUSDT",),
                coin_targets_map={},
                coin_prices={"ETHUSDT": 3000.0},
                phase_a_plans=[],
                phase_b_plans=[],
                executed_orders_summary=[],
                is_healthy_rebalance=True,
            ))
        ex.execute_smart_rebalance_order.assert_not_awaited()

    def test_conditional_algo_stop_market_detection_and_cancellation(self):
        """Binance USD-M CONDITIONAL STOP_MARKET (o['type']=='market', info['orderType']=='STOP_MARKET') коректно скасовується."""
        self.mock_ccxt.fetch_open_orders = MagicMock(side_effect=lambda sym, params=None: (
            [{
                "id": "1000000304073863",
                "type": "market",
                "info": {"algoType": "CONDITIONAL", "orderType": "STOP_MARKET", "triggerPrice": "0.9623"},
            }] if (params and params.get("trigger")) else []
        ))
        self.mock_ccxt.cancel_order = MagicMock()
        self.mock_ccxt.create_order = MagicMock(return_value={"id": "new_sl_1"})

        ok1, st1 = self.exchange_service._place_stop_loss_ex_sync("XRPUSDT", -29.3, 0.9623)
        self.assertTrue(ok1)
        self.assertEqual(st1, "OK")
        self.mock_ccxt.cancel_order.assert_called_once_with("1000000304073863", "XRP/USDT:USDT", params={"trigger": True})

        # Bulk fapiPrivateGetOpenAlgoOrders за 1 REST-запит повертає CONDITIONAL STOP_MARKET для всіх монет
        class _FakeBinanceBulkEx:
            def fetch_open_orders(self, sym=None, params=None):
                return []

            def fapiPrivateGetOpenAlgoOrders(self):
                return [{
                    "algoId": 1000000304412671,
                    "clientAlgoId": "qc6_XRPUSDT_BR_1",
                    "algoType": "CONDITIONAL",
                    "orderType": "STOP_MARKET",
                    "symbol": "XRPUSDT",
                    "side": "BUY",
                    "triggerPrice": "0.9623",
                }]

        self.exchange_service._exchange = _FakeBinanceBulkEx()
        bulk_map = self.exchange_service._fetch_all_open_orders_by_symbol_sync(("XRPUSDT", "SOLUSDT"))
        self.assertEqual(len(bulk_map["XRPUSDT"]), 1)
        self.assertEqual(self.exchange_service._extract_order_type(bulk_map["XRPUSDT"][0]), "stop_market")
        self.assertEqual(len(bulk_map["SOLUSDT"]), 0)

    def test_v62b_exchange_smart_maker_delegation_l1_ticker_and_min_notional_bypass(self):
        """V6.2-B інтеграція: дефолт SMART_MAKER_CHASE_ENABLED=False; при увімкненні використовує L1 ticker (0 fetch_order_book), GTX postOnly та поріг $15."""
        from app.core.config import settings
        self.assertFalse(settings.SMART_MAKER_CHASE_ENABLED)

        self.mock_ccxt.fetch_ticker = MagicMock(return_value={"bid": 99.95, "ask": 100.05})
        self.mock_ccxt.fetch_order_book = MagicMock(side_effect=AssertionError("fetch_order_book must NOT be called by SmartMakerExecutor!"))
        self.mock_ccxt.create_order = MagicMock(return_value={
            "id": "gtx_sol_1", "status": "closed", "filled": 0.5, "average": 99.95,
        })
        self.mock_ccxt.create_market_order = MagicMock(return_value={
            "id": "mkt_sol_small", "status": "closed", "filled": 0.1, "average": 100.05,
        })

        orig_sm = settings.SMART_MAKER_CHASE_ENABLED
        object.__setattr__(settings, "SMART_MAKER_CHASE_ENABLED", True)
        try:
            # 1) Ордер $50 (>= $15) з allow_smart_maker=True -> GTX postOnly без fetch_order_book!
            dto_big = asyncio.run(self.exchange_service.execute_smart_rebalance_order(
                symbol="SOLUSDT", delta_qty=0.5, mark_price=100.0, note="SM entry", reduce_only=False, allow_smart_maker=True,
            ))
            self.assertIsNotNone(dto_big)
            self.assertTrue(dto_big.is_maker)
            _, c_kw = self.mock_ccxt.create_order.call_args
            self.assertEqual(c_kw["params"]["timeInForce"], "GTX")
            self.assertTrue(c_kw["params"]["postOnly"])
            diag_big = self.exchange_service.get_last_order_diag("SOLUSDT")
            self.assertEqual(diag_big["exec_mode"], "smart_maker")
            self.assertAlmostEqual(diag_big["implementation_shortfall_bps"], -3.0, places=3)

            # 2) Малий вхід $10 (< $15 SMART_MAKER_MIN_NOTIONAL_USD, але >= $5 minNotional) -> прямий MARKET без chase!
            self.mock_ccxt.create_order.reset_mock()
            dto_small = asyncio.run(self.exchange_service.execute_smart_rebalance_order(
                symbol="SOLUSDT", delta_qty=0.1, mark_price=100.0, note="Small entry", reduce_only=False, allow_smart_maker=True,
            ))
            self.assertIsNotNone(dto_small)
            self.mock_ccxt.create_order.assert_not_called()
            self.mock_ccxt.create_market_order.assert_called_once()
            diag_small = self.exchange_service.get_last_order_diag("SOLUSDT")
            self.assertEqual(diag_small["exec_mode"], "market_direct")
        finally:
            object.__setattr__(settings, "SMART_MAKER_CHASE_ENABLED", orig_sm)


if __name__ == "__main__":
    unittest.main()
