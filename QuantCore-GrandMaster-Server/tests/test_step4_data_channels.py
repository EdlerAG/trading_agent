import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import numpy as np

from app.core.config import settings
from app.core.http_client import SharedHttpClient
from app.domain.schemas import CoinStateDTO
from app.services.market_data_service import MarketDataService
from app.services.news_ai_service import NewsAiService
from app.cartridges.v58_grand_master_cartridge import V58GrandMasterCartridge


class TestStep4DataChannels(unittest.IsolatedAsyncioTestCase):
    async def test_market_data_funding_injection(self):
        """Перевірка паралельного завантаження funding rates та інжекції в df['funding_rate']."""
        logger = MagicMock()
        exchange = MagicMock()

        # Mock candles DataFrame
        n_bars = 210
        dates = pd.date_range("2026-01-01", periods=n_bars, freq="15min")
        df_btc = pd.DataFrame({
            "open": np.full(n_bars, 50000.0),
            "high": np.full(n_bars, 50500.0),
            "low": np.full(n_bars, 49800.0),
            "close": np.full(n_bars, 50200.0),
            "volume": np.full(n_bars, 100.0),
            "quote_volume": np.full(n_bars, 5020000.0),
            "taker_buy_volume": np.full(n_bars, 50.0),
            "timestamp": dates,
        })

        exchange.fetch_delta_candles = AsyncMock(return_value=df_btc.copy())
        exchange.fetch_funding_rates = AsyncMock(return_value={"BTCUSDT": 0.00015, "ETHUSDT": -0.00005})

        md_service = MarketDataService(logger, exchange)
        candles = await md_service.fetch_synchronized_candles(("BTCUSDT",), min_bars=200)

        self.assertIn("BTCUSDT", candles)
        self.assertIn("funding_rate", candles["BTCUSDT"].columns)
        self.assertAlmostEqual(candles["BTCUSDT"]["funding_rate"].iloc[-1], 0.00015, places=5)
        exchange.fetch_funding_rates.assert_awaited_once_with(("BTCUSDT",))

    async def test_news_ai_structured_parsing_and_geo_shock(self):
        """Перевірка парсингу структурованого сентименту та детекції R5 Geo-Macro Shock."""
        news_service = NewsAiService()

        sample_gemini_json = (
            '{\n'
            '  "macro_sentiment": -0.65,\n'
            '  "geo_shock_prob": 0.85,\n'
            '  "coin_bias": {"BTC": -0.70, "ETH": -0.80, "SOL": -0.50}\n'
            '}'
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": sample_gemini_json}]
                }
            }]
        }

        orig_enabled = settings.ENABLE_NEWS_SENTIMENT
        orig_key = settings.GEMINI_API_KEY
        object.__setattr__(settings, "ENABLE_NEWS_SENTIMENT", True)
        object.__setattr__(settings, "GEMINI_API_KEY", "test_key")

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        try:
            with patch.object(NewsAiService, "fetch_headlines", AsyncMock(return_value=["War escalation shock", "Major exchange audited"])), \
                 patch.object(SharedHttpClient, "get", return_value=mock_client):

                intel = await news_service.fetch_market_intelligence(force_refresh=True)

                self.assertAlmostEqual(intel["macro_sentiment"], -0.65, places=2)
                self.assertAlmostEqual(intel["geo_shock_prob"], 0.85, places=2)
                self.assertTrue(intel["is_geo_shock"])
                self.assertTrue(news_service.is_geo_shock)
                self.assertIn("BTC", intel["coin_bias"])
                self.assertAlmostEqual(intel["coin_bias"]["BTC"], -0.70, places=2)
        finally:
            object.__setattr__(settings, "ENABLE_NEWS_SENTIMENT", orig_enabled)
            object.__setattr__(settings, "GEMINI_API_KEY", orig_key)

    def test_cartridge_r5_activation_on_geo_shock(self):
        """Перевірка активації режиму R5: Geo-Macro Shock у V58Cartridge при geo_shock_override=True."""
        cartridge = V58GrandMasterCartridge(filename="test_v58.pkl", bundle={})

        n_bars = 210
        dates = pd.date_range("2026-01-01", periods=n_bars, freq="15min")
        df_btc = pd.DataFrame({
            "open": np.full(n_bars, 60000.0),
            "high": np.full(n_bars, 60500.0),
            "low": np.full(n_bars, 59500.0),
            "close": np.full(n_bars, 60000.0),
            "volume": np.full(n_bars, 100.0),
            "quote_volume": np.full(n_bars, 6000000.0),
            "taker_buy_volume": np.full(n_bars, 50.0),
            "timestamp": dates,
            "funding_rate": np.full(n_bars, 0.0001),
        })

        candles_map = {"BTCUSDT": df_btc}
        coin_states = {"BTCUSDT": CoinStateDTO(symbol="BTCUSDT")}

        res = cartridge.compute_portfolio_targets(
            candles_map=candles_map,
            coin_states=coin_states,
            online_weights={},
            max_portfolio_lev=1.0,
            orchestrator_mode="PORTFOLIO_SYNERGY",
            news_sentiment=-0.5,
            funding_rates_map={"BTCUSDT": 0.0001},
            geo_shock_override=True,
            coin_bias={"BTC": -0.6},
        )

        self.assertTrue(res.extra_telemetry.get("geo_shock_active"))
        # У режимі R5 лонг-позиції не відкриваються
        self.assertLessEqual(res.targets["BTCUSDT"].desired_weight, 0.0)


if __name__ == "__main__":
    unittest.main()
