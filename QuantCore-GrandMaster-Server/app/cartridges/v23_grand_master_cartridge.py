from typing import Dict, Any, Tuple, List, Optional
import numpy as np
import pandas as pd
from app.domain.interfaces import IAlphaCartridge
from app.domain.schemas import CoinStateDTO, CoinTargetDTO, PortfolioTargetDTO
from app.cartridges.feature_pipe_v23 import (
    FEATURE_COLS_V23,
    compute_core_market_breadth,
    compute_v23_features_float32,
)


def _run_pod2_breakout_sniper_tail(
    close_arr: np.ndarray,
    tsmom_24: np.ndarray,
    tsmom_48: np.ndarray,
    donch_96: np.ndarray,
    donch_384: np.ndarray,
    ker_96: np.ndarray,
    taker_32: np.ndarray,
    z64_arr: np.ndarray,
    spread_macro: np.ndarray,
    bull_d_th: float,
    bear_d_th: float,
) -> np.ndarray:
    """Швидкий тактичний снайпер пробоїв Дончіана (Pod 2) на хвості з 350 свічок."""
    n = len(close_arr)
    pos_arr = np.zeros(n, dtype=np.float64)
    pos = 0.0
    entry_price = 0.0
    highest = 0.0
    lowest = 1e12
    bars_held = 0
    cooldown = 0

    for i in range(1, n):
        c = float(close_arr[i])
        m24, m48 = float(tsmom_24[i]), float(tsmom_48[i])
        d96, d384 = float(donch_96[i]), float(donch_384[i])
        k96, t32 = float(ker_96[i]), float(taker_32[i])
        z64, sm = float(z64_arr[i]), float(spread_macro[i])

        if cooldown > 0:
            cooldown -= 1

        if pos == 0.0:
            if cooldown == 0:
                if (d96 > bull_d_th) and (m48 > 0.55) and (k96 > 0.14) and (t32 > 0.05) and (sm > -0.35) and (z64 < 2.2):
                    pos = 1.0
                    entry_price = c
                    highest = c
                    bars_held = 0
                elif (d96 < -bear_d_th) and (d384 < -0.60) and (m48 < -0.75) and (t32 < -0.08) and (sm < -0.10) and (z64 > -1.9):
                    pos = -1.0
                    entry_price = c
                    lowest = c
                    bars_held = 0
        elif pos > 0.0:
            bars_held += 1
            if c > highest:
                highest = c
            gain = (c - entry_price) / max(1e-8, entry_price)
            drawback = (highest - c) / max(1e-8, highest)
            if ((highest > entry_price * 1.022) and (drawback >= 0.011)) or (bars_held >= 12 and m24 < -0.15 and d96 < 0.0) or (gain <= -0.016):
                pos = 0.0
                cooldown = 8
        elif pos < 0.0:
            bars_held += 1
            if c < lowest:
                lowest = c
            short_gain = (entry_price - c) / max(1e-8, entry_price)
            bounce = (c - lowest) / max(1e-8, lowest)
            if (z64 < -2.15 and short_gain > 0.012) or (lowest < entry_price * 0.975 and bounce >= 0.010) or (bars_held >= 8 and m24 > 0.20) or (short_gain <= -0.015):
                pos = 0.0
                cooldown = 12

        pos_arr[i] = pos
    return pos_arr


def _simulate_cascade_tail(
    close_arr: np.ndarray,
    sig_macro: np.ndarray,
    sig_ml: np.ndarray,
    pod2_breakout: np.ndarray,
    ker_192: np.ndarray,
    z96_arr: np.ndarray,
    rs_96_arr: np.ndarray,
    vwap_dist_arr: np.ndarray,
    en_macro_th: float,
    en_ml_th: float,
    w_macro: float,
    w_break: float,
    w_ml: float,
    max_long_cap: float,
    max_short_cap: float,
    mode_flag: int,
) -> Tuple[float, int]:
    """Симулює Каскад Фаз (F0..F4) на хвості свічок і повертає актуальну позицію та фазу."""
    if mode_flag == 0:
        return 0.0, 0

    n = len(close_arr)
    macro_state = 0.0
    macro_held = 0
    ml_state = 0.0
    ml_held = 0
    raw = 0.0
    phase = 0

    for i in range(n):
        sm = float(sig_macro[i])
        sml = float(sig_ml[i])
        p2 = float(pod2_breakout[i]) if mode_flag != 4 else 0.0
        k = float(ker_192[i])
        z96 = float(z96_arr[i])
        rs = float(rs_96_arr[i])
        vd = float(vwap_dist_arr[i])

        if macro_state == 0.0:
            if sm >= en_macro_th and k >= 0.05:
                macro_state = 0.85 if sm < (en_macro_th + 0.18) else 1.25
                macro_held = 0
        else:
            macro_held += 1
            if sm <= -0.05 and (macro_held >= 44 or sm <= -0.15):
                macro_state = 0.0
            elif macro_state < 1.20 and ((sm >= en_macro_th + 0.18) or (sm >= en_macro_th + 0.04 and (z96 < -0.55 or vd < -0.45))):
                macro_state = 1.25

        if ml_state == 0.0:
            if sml >= en_ml_th and sm > -0.10 and k >= 0.05:
                ml_state = 1.0
                ml_held = 0
            elif sml <= -0.36 and sm <= 0.0 and k >= 0.08:
                ml_state = -0.80
                ml_held = 0
        elif ml_state > 0.0:
            ml_held += 1
            if (sml <= -0.02 and ml_held >= 32) or (sml <= -0.16):
                ml_state = 0.0
        elif ml_state < 0.0:
            ml_held += 1
            if (sml >= 0.02 and ml_held >= 20) or (sml >= 0.14):
                ml_state = 0.0

        if p2 < 0.0 and macro_state == 0.0:
            rs_short_boost = 1.15 if rs < -0.20 else 1.0
            raw = (w_break * p2 + w_ml * min(0.0, ml_state)) * rs_short_boost
            phase = -1
        else:
            raw = w_macro * macro_state + w_break * max(0.0, p2) + w_ml * max(0.0, ml_state)
            if raw > 0.80 and rs > 0.35:
                raw *= 1.12

            if raw <= 0.02:
                phase = 0
            elif raw < 0.90:
                phase = 1
            elif raw < 1.65:
                phase = 2
            else:
                phase = 3

        if mode_flag == 2 and raw < 0.0:
            raw = 0.0
            if phase < 0:
                phase = 0
        elif mode_flag == 3 and raw > 0.0:
            raw = 0.0
            if phase > 0:
                phase = 0

        if raw > max_long_cap:
            raw = max_long_cap
        elif raw < -max_short_cap:
            raw = -max_short_cap

    return float(raw), int(phase)


class V23GrandMasterCartridge(IAlphaCartridge):
    """
    Бойовий картридж для мультивалютних моделей V23.0 Grand-Master (та сумісних V13..V22).
    Працює за 0.05 сек у 1-потоковому режимі та інтегрує онлайн-ваги самонавчання (MWU + Bandit).
    """

    __slots__ = ("_filename", "_arch", "_symbols", "_feature_names", "_assets_dict", "_matrix_cfg")

    def __init__(self, filename: str, bundle: Dict[str, Any]) -> None:
        self._filename: str = filename
        self._arch: str = str(bundle.get("architecture", "QuantCore_V23_0_Grand_Master_Production"))
        raw_syms = bundle.get("symbols") or list(bundle.get("assets", {}).keys())
        self._symbols: Tuple[str, ...] = tuple(str(s).upper() for s in raw_syms)
        self._feature_names: List[str] = list(bundle.get("feature_names", FEATURE_COLS_V23))
        self._assets_dict: Dict[str, Any] = bundle.get("assets", {})
        self._matrix_cfg: Dict[str, Any] = bundle.get("currency_control_matrix", {})

    @property
    def architecture_name(self) -> str:
        return self._arch

    @property
    def supported_symbols(self) -> Tuple[str, ...]:
        return self._symbols

    def _predict_ml_tail(
        self,
        sym: str,
        X_tail: np.ndarray,
        models_dict: Dict[str, Any],
        orchestrator_mode: str,
        online_asset_state: Dict[str, Any],
    ) -> Tuple[np.ndarray, List[float]]:
        """
        Обчислює вектор ML-сигналу на останніх 350 свічках. Якщо зовнішній .joblib
        ще не завантажено, повертає нульовий вектор ML, дозволяючи працювати структурному ядру V23.
        """
        if not models_dict or "scaler" not in models_dict:
            return np.zeros(len(X_tail), dtype=np.float64), []

        scaler = models_dict["scaler"]
        X_scaled = np.clip(scaler.transform(X_tail), -4.0, 4.0)

        p_ridge = models_dict["ridge"].predict(X_scaled)
        p_lgbm = models_dict["lgbm"].predict(X_scaled, n_jobs=1)
        p_cb = models_dict["catboost"].predict(X_scaled, thread_count=1)
        p_hgb = models_dict["hgb"].predict(X_scaled)
        p_mlp = models_dict["mlp"].predict(X_scaled)
        huber_model = models_dict.get("huber")

        # 5-Model Classic Stacker
        stack_5 = np.column_stack([p_ridge, p_lgbm, p_cb, p_hgb, p_mlp])
        w5_base = np.asarray(models_dict.get("w5") or models_dict.get("w5_classic") or models_dict.get("meta_weights", [0.30, 0.25, 0.25, 0.10, 0.10]), dtype=np.float64)
        if len(w5_base) != 5:
            w5_base = np.array([0.30, 0.25, 0.25, 0.10, 0.10], dtype=np.float64)

        b5_online = online_asset_state.get("bandit_5_weights")
        if b5_online and len(b5_online) == 5:
            w5 = 0.80 * w5_base + 0.20 * np.asarray(b5_online, dtype=np.float64)
            w5 /= max(1e-8, np.sum(w5))
        else:
            w5 = w5_base

        pm5 = float(models_dict.get("pm5", models_dict.get("pred_mean", 0.0)))
        ps5 = float(models_dict.get("ps5", models_dict.get("pred_std", 1.0)))
        z5 = np.tanh(((stack_5 @ w5 - pm5) / (ps5 + 1e-8)) * 0.65)
        sig_5 = pd.Series(z5).ewm(span=32, adjust=False).mean().values

        # 6-Model Huber Stacker (якщо присутній у бандлі V19..V23)
        if huber_model is not None:
            p_huber = huber_model.predict(X_scaled)
            stack_6 = np.column_stack([p_ridge, p_huber, p_lgbm, p_cb, p_hgb, p_mlp])
            w6_base = np.asarray(models_dict.get("w6") or models_dict.get("w6_huber") or models_dict.get("meta_weights", [0.20, 0.20, 0.15, 0.25, 0.10, 0.10]), dtype=np.float64)
            if len(w6_base) != 6:
                w6_base = np.array([0.20, 0.20, 0.15, 0.25, 0.10, 0.10], dtype=np.float64)

            b6_online = online_asset_state.get("bandit_6_weights")
            if b6_online and len(b6_online) == 6:
                w6 = 0.80 * w6_base + 0.20 * np.asarray(b6_online, dtype=np.float64)
                w6 /= max(1e-8, np.sum(w6))
            else:
                w6 = w6_base

            pm6 = float(models_dict.get("pm6", models_dict.get("pred_mean", 0.0)))
            ps6 = float(models_dict.get("ps6", models_dict.get("pred_std", 1.0)))
            z6 = np.tanh(((stack_6 @ w6 - pm6) / (ps6 + 1e-8)) * 0.65)
            sig_6 = pd.Series(z6).ewm(span=32, adjust=False).mean().values
            latest_subpreds = [float(p_ridge[-1]), float(p_huber[-1]), float(p_lgbm[-1]), float(p_cb[-1]), float(p_hgb[-1]), float(p_mlp[-1])]
        else:
            sig_6 = sig_5
            latest_subpreds = [float(p_ridge[-1]), float(p_lgbm[-1]), float(p_cb[-1]), float(p_hgb[-1]), float(p_mlp[-1])]

        # Вибір ядра залежно від режиму оркестратора (PORTFOLIO_SYNERGY або SOLO_MAX)
        k_name = models_dict.get("portfolio_kernel" if orchestrator_mode == "PORTFOLIO_SYNERGY" else "solo_kernel")
        if not k_name:
            k_name = models_dict.get("kernel_type") or models_dict.get("arch_mode") or "V19_HUBER_IC"

        if k_name == "V18_CLASSIC":
            return sig_5, latest_subpreds
        elif k_name == "V21_DUAL_75":
            return (0.25 * sig_5 + 0.75 * sig_6), latest_subpreds
        elif "kernel_blend" in models_dict:
            kb = float(models_dict["kernel_blend"])
            return ((1.0 - kb) * sig_5 + kb * sig_6), latest_subpreds
        return sig_6, latest_subpreds

    def compute_portfolio_targets(
        self,
        candles_map: Dict[str, pd.DataFrame],
        coin_states: Dict[str, CoinStateDTO],
        online_weights: Dict[str, Dict[str, Any]],
        max_portfolio_lev: float,
        orchestrator_mode: str = "PORTFOLIO_SYNERGY",
        news_sentiment: float = 0.0,
    ) -> PortfolioTargetDTO:
        btc_close, core_breadth = compute_core_market_breadth(candles_map)
        latest_breadth = float(core_breadth.iloc[-1]) if len(core_breadth) > 0 else 0.0
        candle_ts = ""

        coin_calc: Dict[str, Dict[str, Any]] = {}
        active_syms = [s for s in self._symbols if s in candles_map and len(candles_map[s]) >= 1650]

        for sym in active_syms:
            df_sym = candles_map[sym]
            if not candle_ts and "timestamp" in df_sym.columns:
                candle_ts = str(df_sym["timestamp"].iloc[-1])

            feats_df = compute_v23_features_float32(df_sym, btc_close, core_breadth)
            tail_df = feats_df.iloc[-350:].reset_index(drop=True)

            asset_bundle = self._assets_dict.get(sym, {})
            models_dict = asset_bundle.get("models", {})
            c_state = coin_states.get(sym)
            online_st = online_weights.get(sym, {})

            mode_flag = int(c_state.mode) if (c_state and c_state.enabled) else 0
            max_l = float(c_state.max_long_lev) if c_state else 2.40
            max_s = float(c_state.max_short_lev) if c_state else 1.25
            base_w = float(c_state.base_weight) if c_state else 1.00
            role = int(c_state.tier_role) if c_state else 1
            cur_pos_qty = float(c_state.current_pos_qty) if c_state else 0.0

            X_tail = np.ascontiguousarray(tail_df[self._feature_names].values, dtype=np.float32)
            sig_ml_vec, latest_subpreds = self._predict_ml_tail(sym, X_tail, models_dict, orchestrator_mode, online_st)

            # Розрахунок структурного ядра Macro Ultra на хвості 350 свічок
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
            sig_macro_ultra = 0.82 * pd.Series(sig_v7_8_raw).ewm(span=16, adjust=False).mean().values + 0.18 * sig_ml_vec

            if news_sentiment <= -0.75:
                sig_macro_ultra = np.where(sig_macro_ultra > 0, sig_macro_ultra * 0.75, sig_macro_ultra)

            c_cfg_key = "portfolio_cascade_config" if orchestrator_mode == "PORTFOLIO_SYNERGY" else "solo_cascade_config"
            c_cfg = asset_bundle.get(c_cfg_key) or asset_bundle.get("cascade_config", {})
            bd_th = float(c_cfg.get("bull_d_th", 0.72))
            brd_th = float(c_cfg.get("bear_d_th", 0.77))
            en_mac = float(c_cfg.get("en_macro_th", 0.35))
            en_ml = float(c_cfg.get("en_ml_th", 0.24))
            wm = float(c_cfg.get("w_macro", 0.80))
            wb = float(c_cfg.get("w_break", 0.85))
            wml = float(c_cfg.get("w_ml", 0.70))

            close_tail = tail_df["close"].values.astype(np.float64)
            p2_vec = _run_pod2_breakout_sniper_tail(
                close_tail,
                tail_df["tsmom_24"].values,
                tail_df["tsmom_48"].values,
                tail_df["donchian_96"].values,
                donch384,
                tail_df["ker_raw_96"].values,
                tail_df["taker_imb_32"].values,
                tail_df["zscore_64"].values,
                spread_macro,
                bd_th,
                brd_th,
            )

            raw_pos, phase_id = _simulate_cascade_tail(
                close_tail,
                sig_macro_ultra,
                sig_ml_vec,
                p2_vec,
                tail_df["ker_raw_192"].values,
                z96,
                tail_df["rs_vs_btc_96"].values,
                tail_df["dist_vwap_96"].values,
                en_mac,
                en_ml,
                wm,
                wb,
                wml,
                max_l,
                max_s,
                mode_flag,
            )

            latest_sm = float(sig_macro_ultra[-1])
            latest_sml = float(sig_ml_vec[-1])
            latest_rs = float(tail_df["rs_vs_btc_96"].iloc[-1])
            latest_z96 = float(z96[-1])
            latest_ker = float(tail_df["ker_raw_192"].iloc[-1])
            latest_price = float(close_tail[-1])
            latest_atr = float(tail_df["atr"].iloc[-1])
            alpha_sc = 0.45 * latest_sm + 0.35 * latest_sml + 0.20 * latest_rs

            mwu_mult = float(online_st.get("online_mult", 1.05))
            sticky_bonus = 0.03 if abs(cur_pos_qty) > 0.0 else 0.0
            eff_sc = alpha_sc * base_w * mwu_mult + sticky_bonus

            coin_calc[sym] = {
                "raw_pos": raw_pos,
                "phase": phase_id,
                "alpha_score": alpha_sc,
                "eff_sc": eff_sc,
                "sig_macro": latest_sm,
                "sig_ml": latest_sml,
                "ker": latest_ker,
                "z96": latest_z96,
                "rs": latest_rs,
                "price": latest_price,
                "atr": latest_atr,
                "base_w": base_w,
                "mwu_mult": mwu_mult,
                "role": role,
                "max_l": max_l,
                "max_s": max_s,
                "mode_flag": mode_flag,
                "subpreds": latest_subpreds,
            }

        if not coin_calc:
            return PortfolioTargetDTO(
                cartridge_name=self._filename,
                architecture=self._arch,
                candle_timestamp=candle_ts,
                market_breadth=latest_breadth,
                news_sentiment=news_sentiment,
                total_gross_leverage=0.0,
                net_leverage=0.0,
                targets={},
            )

        # --- ВЕРХОВНИЙ ОРКЕСТРАТОР V23.0 (STICKY WATERFALL TOP-3 + UTILIZATION + STAT-ARB) ---
        ranked_syms = sorted(coin_calc.keys(), key=lambda s: coin_calc[s]["eff_sc"], reverse=True)
        best_sym = ranked_syms[0]
        second_sym = ranked_syms[1] if len(ranked_syms) > 1 else best_sym
        top3_set = set(ranked_syms[:3])
        worst_sym = min(coin_calc.keys(), key=lambda s: coin_calc[s]["alpha_score"])

        core_active_count = sum(1 for s, d in coin_calc.items() if d["role"] == 1 and d["raw_pos"] > 0.50)

        raw_weights: Dict[str, float] = {s: 0.0 for s in coin_calc}
        total_abs = 0.0

        for s, d in coin_calc.items():
            if d["mode_flag"] == 0 or abs(d["raw_pos"]) < 0.02:
                continue
            sc = d["alpha_score"]
            if s == best_sym and sc > 0.25:
                leader_boost = 1.38
            elif s == second_sym and sc > 0.20:
                leader_boost = 1.22
            elif sc > 0.0:
                leader_boost = 1.00
            else:
                leader_boost = 0.78

            w_s = d["raw_pos"] * 0.52 * d["base_w"] * d["mwu_mult"] * leader_boost
            raw_weights[s] = w_s
            total_abs += abs(w_s)

        # Dynamic Gross Utilization Scaler
        if core_active_count >= 2 and total_abs > 0.40:
            target_util = max_portfolio_lev * 0.88 if core_active_count == 2 else max_portfolio_lev * 0.98
            if total_abs < target_util:
                up_scale = min(1.45, target_util / total_abs)
                total_abs = 0.0
                for s in raw_weights:
                    if coin_calc[s]["role"] <= 2 and raw_weights[s] > 0:
                        raw_weights[s] *= up_scale
                    total_abs += abs(raw_weights[s])

        # Idle-Cash Stat-Arb Spread (у флеті, коли трендові позиції в кеші)
        if total_abs < 0.15 and len(coin_calc) >= 2:
            b_d = coin_calc[best_sym]
            w_d = coin_calc[worst_sym]
            spread_gap = b_d["alpha_score"] - w_d["alpha_score"]
            if (
                b_d["mode_flag"] in (1, 2)
                and w_d["mode_flag"] in (1, 3)
                and spread_gap >= 0.56
                and b_d["alpha_score"] > 0.15
                and w_d["alpha_score"] < -0.16
                and w_d["rs"] < -0.22
            ):
                raw_weights[best_sym] = 0.55 * b_d["base_w"]
                raw_weights[worst_sym] = -0.48 * w_d["base_w"]

        # Panic Capitulation Sniper
        b_d = coin_calc[best_sym]
        if b_d["mode_flag"] in (1, 2) and b_d["z96"] < -2.30 and b_d["alpha_score"] > -0.05 and b_d["role"] <= 2:
            raw_weights[best_sym] += 0.45 * b_d["base_w"]

        # Індивідуальні стелі кожної валюти
        for s, d in coin_calc.items():
            if raw_weights[s] > d["max_l"]:
                raw_weights[s] = d["max_l"]
            elif raw_weights[s] < -d["max_s"]:
                raw_weights[s] = -d["max_s"]

        # Sticky Waterfall Top-3 Router (Топ-3 лідери отримують маржу першими без розмивання!)
        if len(coin_calc) > 3 and orchestrator_mode == "PORTFOLIO_SYNERGY":
            top3_abs = sum(abs(raw_weights[s]) for s in raw_weights if s in top3_set)
            rest_abs = sum(abs(raw_weights[s]) for s in raw_weights if s not in top3_set)

            if (top3_abs + rest_abs) > max_portfolio_lev:
                if top3_abs >= max_portfolio_lev * 0.92:
                    scale_top = (max_portfolio_lev * 0.94) / max(1e-6, top3_abs)
                    scale_rest = (max_portfolio_lev * 0.06) / max(1e-6, rest_abs) if rest_abs > 1e-6 else 0.0
                    for s in raw_weights:
                        raw_weights[s] *= scale_top if s in top3_set else scale_rest
                else:
                    rem_budget = max(0.0, max_portfolio_lev - top3_abs)
                    scale_rest = rem_budget / max(1e-6, rest_abs) if rest_abs > 1e-6 else 0.0
                    for s in raw_weights:
                        if s not in top3_set:
                            raw_weights[s] *= scale_rest
        else:
            tot_a = sum(abs(v) for v in raw_weights.values())
            if tot_a > max_portfolio_lev and tot_a > 1e-6:
                sc_f = max_portfolio_lev / tot_a
                for s in raw_weights:
                    raw_weights[s] *= sc_f

        targets_out: Dict[str, CoinTargetDTO] = {}
        gross_lev = 0.0
        net_lev = 0.0

        for s, d in coin_calc.items():
            w_final = round(float(raw_weights[s]), 4)
            gross_lev += abs(w_final)
            net_lev += w_final
            targets_out[s] = CoinTargetDTO(
                symbol=s,
                desired_weight=w_final,
                raw_model_pos=round(d["raw_pos"], 4),
                phase=d["phase"],
                alpha_score=round(d["alpha_score"], 4),
                signal_macro=round(d["sig_macro"], 4),
                signal_ml=round(d["sig_ml"], 4),
                ker_purity=round(d["ker"], 4),
                zscore_96=round(d["z96"], 4),
                rs_vs_btc=round(d["rs"], 4),
                current_price=round(d["price"], 4),
                atr_14=round(d["atr"], 4),
                raw_submodel_preds=d["subpreds"],
            )

        return PortfolioTargetDTO(
            cartridge_name=self._filename,
            architecture=self._arch,
            candle_timestamp=candle_ts,
            market_breadth=round(latest_breadth, 3),
            news_sentiment=round(news_sentiment, 3),
            total_gross_leverage=round(gross_lev, 3),
            net_leverage=round(net_lev, 3),
            targets=targets_out,
            extra_telemetry={
                "top_leader": best_sym,
                "second_leader": second_sym,
                "core_active_count": core_active_count,
                "orchestrator_mode": orchestrator_mode,
            },
        )