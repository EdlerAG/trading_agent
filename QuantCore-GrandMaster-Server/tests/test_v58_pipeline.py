import sys
import os
import unittest
import numpy as np
import pandas as pd

# Add server root to sys.path
server_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from app.cartridges.feature_pipe_v58 import (
    ORTHO_FEATURE_NAMES_V58,
    compute_v58_features_float32,
    compute_core_breadth_and_macro,
)
from app.cartridges.v58_grand_master_cartridge import V58GrandMasterCartridge


class TestV58Pipeline(unittest.TestCase):

    def test_v58_feature_names_count(self):
        self.assertEqual(len(ORTHO_FEATURE_NAMES_V58), 55, f"Expected 55 features, got {len(ORTHO_FEATURE_NAMES_V58)}")

    def test_v58_feature_calculation_and_shape(self):
        n_bars = 250
        np.random.seed(42)
        p0 = 65000.0
        rets = np.random.normal(0.0002, 0.005, n_bars)
        prices = p0 * np.exp(np.cumsum(rets))
        highs = prices * 1.002
        lows = prices * 0.998
        opens = np.roll(prices, 1)
        opens[0] = p0
        vols = np.random.uniform(100.0, 500.0, n_bars)
        tb = vols * 0.5

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": vols,
            "taker_base": tb,
            "timestamp": pd.date_range("2026-01-01", periods=n_bars, freq="15min"),
        })

        candles_map = {"BTCUSDT": df, "ETHUSDT": df.copy()}
        btc_c, core_b, cont_b, cross_d, geo_s = compute_core_breadth_and_macro(candles_map)

        feats_df, atr_ser = compute_v58_features_float32(
            df=df,
            btc_close=btc_c,
            eth_close=btc_c,
            core_breadth=core_b,
            cont_breadth_z=cont_b,
            cross_disp=cross_d,
            geo_shock=geo_s,
        )

        self.assertEqual(feats_df.shape[1], 55)
        self.assertEqual(feats_df.shape[0], n_bars)
        self.assertFalse(feats_df.isna().any().any(), "Features matrix must not contain any NaNs")
        self.assertEqual(len(atr_ser), n_bars)

    def test_v58_cartridge_evaluation(self):
        n_bars = 250
        df = pd.DataFrame({
            "open": np.linspace(60000, 65000, n_bars),
            "high": np.linspace(60100, 65100, n_bars),
            "low": np.linspace(59900, 64900, n_bars),
            "close": np.linspace(60050, 65050, n_bars),
            "volume": np.full(n_bars, 1000.0),
            "taker_base": np.full(n_bars, 500.0),
            "timestamp": pd.date_range("2026-01-01", periods=n_bars, freq="15min"),
        })

        cart = V58GrandMasterCartridge(
            filename="v58_test",
            bundle={"symbols": ["BTCUSDT"], "assets": {}},
        )

        self.assertIn("V58", cart.architecture_name)
        candles = {"BTCUSDT": df}
        res = cart.compute_portfolio_targets(candles, {}, {}, 3.0)
        self.assertIn("BTCUSDT", res.targets)
        self.assertIsInstance(res.targets["BTCUSDT"].desired_weight, float)


if __name__ == "__main__":
    unittest.main()

