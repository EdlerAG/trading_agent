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


if __name__ == "__main__":
    unittest.main()
