from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
from app.domain.interfaces import IAlphaCartridge
from app.domain.schemas import CoinStateDTO, CoinTargetDTO, PortfolioTargetDTO
from app.cartridges.feature_pipe_v23 import (
    FEATURE_COLS_V7_8,
    compute_v7_8_features_float32,
)


class LegacyV7CartridgeAdapter(IAlphaCartridge):
    """
    Адаптер, який огортає старий одномонетний бандл QuantCore V7.8 Ultra (quant_core_production.joblib)
    під універсальний мультивалютний контракт IAlphaCartridge.
    """

    __slots__ = ("_filename", "_bundle", "_arch")

    def __init__(self, filename: str, bundle: Dict[str, Any]) -> None:
        self._filename: str = filename
        self._bundle: Dict[str, Any] = bundle
        self._arch: str = str(bundle.get("architecture", "QuantCore_V7_8_Ultra_Legacy"))

    @property
    def architecture_name(self) -> str:
        return self._arch

    @property
    def supported_symbols(self) -> Tuple[str, ...]:
        return ("BTCUSDT",)

    def compute_portfolio_targets(
        self,
        candles_map: Dict[str, pd.DataFrame],
        coin_states: Dict[str, CoinStateDTO],
        online_weights: Dict[str, Dict[str, Any]],
        max_portfolio_lev: float,
        orchestrator_mode: str = "PORTFOLIO_SYNERGY",
        news_sentiment: float = 0.0,
    ) -> PortfolioTargetDTO:
        df = candles_map.get("BTCUSDT")
        if df is None or len(df) < 1650:
            return PortfolioTargetDTO(
                cartridge_name=self._filename,
                architecture=self._arch,
                candle_timestamp="",
                market_breadth=0.0,
                news_sentiment=news_sentiment,
                total_gross_leverage=0.0,
                net_leverage=0.0,
                targets={},
            )

        df_feat = compute_v7_8_features_float32(df)
        tail_df = df_feat.iloc[-350:].reset_index(drop=True)
        feature_names = self._bundle.get("feature_names", list(FEATURE_COLS_V7_8))
        X_tail = np.ascontiguousarray(tail_df[feature_names].values, dtype=np.float32)

        if "scaler" in self._bundle and "ridge_model" in self._bundle:
            scaler = self._bundle["scaler"]
            ridge = self._bundle["ridge_model"]
            lgbm = self._bundle["lgbm_model"]
            cb = self._bundle["catboost_model"]
            pm = float(self._bundle.get("pred_mean", 0.0))
            ps = float(self._bundle.get("pred_std", 1.0))

            X_scaled = np.clip(scaler.transform(X_tail), -4.0, 4.0)
            raw_preds = (
                0.40 * ridge.predict(X_scaled) +
                0.30 * lgbm.predict(X_scaled, n_jobs=1) +
                0.30 * cb.predict(X_scaled, thread_count=1)
            )
            ml_z = np.tanh(((raw_preds - pm) / (ps + 1e-8)) * 0.65)
            sig_ml = pd.Series(ml_z).ewm(span=32, adjust=False).mean().values
        else:
            sig_ml = np.zeros(len(tail_df), dtype=np.float64)

        mom_blend = (
            0.10 * tail_df["tsmom_96"].values + 0.20 * tail_df["tsmom_192"].values +
            0.25 * tail_df["tsmom_384"].values + 0.25 * tail_df["tsmom_768"].values +
            0.20 * tail_df["tsmom_1536"].values
        )
        ribbon_blend = (
            0.35 * tail_df["spread_96_384"].values + 0.35 * tail_df["spread_192_768"].values +
            0.30 * tail_df["spread_384_1536"].values
        )
        sig_tsmom = np.tanh(pd.Series(0.55 * mom_blend + 0.45 * ribbon_blend).ewm(span=24, adjust=False).mean().values * 0.85)

        macro_bull = (tail_df["spread_192_768"].values > -0.15) & (tail_df["slope_768"].values > -0.10)
        strong_bull = (tail_df["spread_384_1536"].values > 0.10) & (tail_df["tsmom_768"].values > 0.0)
        deep_bear = (tail_df["spread_384_1536"].values < -0.60) & (tail_df["tsmom_768"].values < -0.50) & (tail_df["slope_768"].values < -0.20)

        z96 = tail_df["zscore_96"].values
        rsi14 = tail_df["rsi_14"].values
        donch384 = tail_df["donchian_384"].values
        donch768 = tail_df["donchian_768"].values
        taker96 = tail_df["taker_imb_96"].values
        taker192 = tail_df["taker_imb_192"].values
        ker288 = tail_df["signed_ker_288"].values
        spread_macro = tail_df["spread_384_1536"].values

        dip_boost = np.maximum(0.0, -z96 * 0.35)
        bull_val = np.where((z96 > 2.6) & (rsi14 > 0.55), 0.10, np.where((donch384 > -0.25) | (z96 < -0.8), np.minimum(1.0, 0.55 + dip_boost), 0.20))
        s_pull = np.where(strong_bull | macro_bull, bull_val, np.where(deep_bear, -0.75, 0.0))
        sig_pullback = pd.Series(s_pull).ewm(span=16, adjust=False).mean().values

        base_blend = 0.52 * sig_tsmom + 0.48 * sig_pullback
        cascade_dump = (donch384 < -0.85) & (taker96 < -0.15) & (tail_df["tsmom_96"].values < -1.2)
        bo_boost = np.where((donch768 > 0.35) & (ker288 > 0.12), 0.18, 0.0)
        of_boost = np.where((taker192 > 0.08) | (taker96 > 0.12), 0.12, 0.0)
        dip_rec = np.where((z96 < -0.50) & (spread_macro > 0.0), 0.12, 0.0)

        sig_v7_8_raw = np.where(cascade_dump, -0.25, np.where(base_blend > 0.0, np.minimum(1.0, base_blend + bo_boost + of_boost + dip_rec), 0.0))
        sig_ultra = 0.82 * pd.Series(sig_v7_8_raw).ewm(span=16, adjust=False).mean().values + 0.18 * sig_ml

        latest_sig = float(sig_ultra[-1])
        if news_sentiment <= -0.75 and latest_sig > 0:
            latest_sig *= 0.75

        latest_ker = float(tail_df["ker_raw_192"].iloc[-1])
        latest_price = float(tail_df["close"].iloc[-1])
        latest_atr = float(tail_df["atr"].iloc[-1])

        c_st = coin_states.get("BTCUSDT")
        mode_flag = int(c_st.mode) if (c_st and c_st.enabled) else 1

        desired_w = 0.0
        phase = 0
        if mode_flag != 0 and latest_sig >= 0.35 and latest_ker >= 0.05:
            desired_w = min(max_portfolio_lev, 0.85 if latest_sig < 0.55 else 1.30)
            phase = 1 if desired_w < 1.0 else 2

        target_dto = CoinTargetDTO(
            symbol="BTCUSDT",
            desired_weight=round(desired_w, 4),
            raw_model_pos=round(desired_w, 4),
            phase=phase,
            alpha_score=round(latest_sig, 4),
            signal_macro=round(latest_sig, 4),
            signal_ml=round(float(sig_ml[-1]), 4),
            ker_purity=round(latest_ker, 4),
            zscore_96=round(float(z96[-1]), 4),
            rs_vs_btc=0.0,
            current_price=round(latest_price, 2),
            atr_14=round(latest_atr, 2),
        )

        return PortfolioTargetDTO(
            cartridge_name=self._filename,
            architecture=self._arch,
            candle_timestamp=str(tail_df["timestamp"].iloc[-1]) if "timestamp" in tail_df.columns else "",
            market_breadth=1.0 if latest_sig > 0.35 else 0.0,
            news_sentiment=news_sentiment,
            total_gross_leverage=abs(desired_w),
            net_leverage=desired_w,
            targets={"BTCUSDT": target_dto},
        )