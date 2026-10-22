import sys
import os
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

# Add server root to sys.path
server_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from app.domain.schemas import CoinStateDTO
from app.services.state_service import StateService
from app.services.ws_sentinel_service import WebSocketSentinelService


class TestWebSocketSentinelService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.logger = MagicMock()
        self.state_service = StateService()
        self.exchange_service = MagicMock()
        self.exchange_service.safe_price = MagicMock(side_effect=lambda sym, p: round(p, 4))
        self.exchange_service.place_or_update_stop_loss = AsyncMock(return_value=True)

        self.event_bus = MagicMock()
        self.event_bus.trigger_wakeup = MagicMock()

        self.sentinel = WebSocketSentinelService(
            logger=self.logger,
            state_service=self.state_service,
            exchange_service=self.exchange_service,
            event_bus_instance=self.event_bus,
        )

        # Setup coin state with BTC
        btc = CoinStateDTO(
            symbol="BTCUSDT",
            enabled=True,
            current_pos_qty=0.5,
            entry_price=100000.0,
            active_sl_price=98000.0,
            is_breakeven=False,
        )
        self.state_service.coins["BTCUSDT"] = btc
        self.sentinel.update_symbol_atr("BTCUSDT", 1000.0)

    async def test_instant_breakeven_long(self):
        """Перевірка перенесення в беззбиток (+0.07%) при досягненні +1.20 ATR."""
        # 100000 + 1.20 * 1000 = 101200
        msg_arr = [{"s": "BTCUSDT", "p": "101250.0"}]
        await self.sentinel._process_mark_price_array(msg_arr)

        btc = self.state_service.coins["BTCUSDT"]
        self.assertTrue(btc.is_breakeven)
        self.exchange_service.place_or_update_stop_loss.assert_called_once()
        expected_be_sl = 100000.0 * 1.0007  # +0.07%
        self.assertAlmostEqual(btc.active_sl_price, expected_be_sl, places=1)

    async def test_chandelier_ratchet_long(self):
        """Перевірка Chandelier Ratchet trailing stop при русі вище +2.0 ATR."""
        btc = self.state_service.coins["BTCUSDT"]
        btc.is_breakeven = True
        btc.active_sl_price = 100070.0

        # Mark price moves to +2.5 ATR: 100000 + 2500 = 102500
        # Desired ratchet SL: 102500 - 1.35 * 1000 = 101150 > 100070 + 200
        msg_arr = [{"s": "BTCUSDT", "p": "102500.0"}]
        await self.sentinel._process_mark_price_array(msg_arr)

        self.assertGreater(btc.active_sl_price, 101000.0)
        self.exchange_service.place_or_update_stop_loss.assert_called_once()

    async def test_flash_crash_detection(self):
        """Перевірка спрацювання Flash-Crash детектора та миттєвого WAKEUP при русі > 2.2 ATR."""
        import time
        self.sentinel._candle_bucket = int(time.time() // 900)
        # Baseline price: 100000.0
        self.sentinel._candle_open_prices["BTCUSDT"] = 100000.0
        # Dump by 2400 (> 2.2 * 1000 = 2200)
        msg_arr = [{"s": "BTCUSDT", "p": "97600.0"}]
        await self.sentinel._process_mark_price_array(msg_arr)

        self.event_bus.trigger_wakeup.assert_called_once()

    async def test_stink_bid_protection(self):
        """Перевірка миттєвого виставлення STOP_MARKET при наливі stink-bid."""
        self.sentinel.register_stink_bid("BTCUSDT", qty=0.2, price=95000.0, atr=1000.0)
        self.assertEqual(len(self.sentinel._active_stink_bids), 1)

        # Price pierces below 95000.0
        msg_arr = [{"s": "BTCUSDT", "p": "94950.0"}]
        await self.sentinel._process_mark_price_array(msg_arr)

        # STOP_MARKET must be placed at 95000 - 1.35 * 1000 = 93650
        self.exchange_service.place_or_update_stop_loss.assert_called_with("BTCUSDT", 0.2, 93650.0)
        self.assertEqual(len(self.sentinel._active_stink_bids), 0)


if __name__ == "__main__":
    unittest.main()
