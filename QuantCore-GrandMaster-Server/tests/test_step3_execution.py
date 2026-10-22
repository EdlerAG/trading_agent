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


if __name__ == "__main__":
    unittest.main()
