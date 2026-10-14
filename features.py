import math
import numpy as np
import pandas as pd
import config


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean().bfill()


def _wilder_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    ema_up = up.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    ema_down = down.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = ema_up / ema_down.replace(0.0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def calculate_v7_8_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Zero-Fragmentation розрахунок 40 інституційних факторів QuantCore V7.8 Ultra.
    Збирає всі вектори в пам'яті за один прохід без фрагментації DataFrame.
    """
    if len(df) < 1700:
        raise ValueError(f"❌ Недостатньо свічок ({len(df)} < 1700) для прогріву EMA-1536!")

    c = df['close'].astype(float)
    h = df['high'].astype(float)
    l = df['low'].astype(float)
    v = df['volume'].astype(float)

    f = {}

    # 1. Волатильність
    log_ret = np.log(c / c.shift(1)).fillna(0.0)
    vol_96 = log_ret.rolling(96).std().replace(0, np.nan).bfill()
    vol_384 = log_ret.rolling(384).std().replace(0, np.nan).bfill()

    atr_14 = _wilder_atr(h, l, c, 14)
    atr_96 = _wilder_atr(h, l, c, 96)
    safe_atr96 = atr_96.replace(0, np.nan).bfill()

    f['vol_96'] = vol_96
    f['vol_ratio_96_384'] = np.clip((vol_96 / vol_384).fillna(1.0), 0.3, 3.0)

    # 2. Time-Series Momentum (48 .. 1536)
    for w in [48, 96, 192, 384, 768, 1536]:
        ret_w = np.log(c / c.shift(w)).fillna(0.0)
        f[f'tsmom_{w}'] = np.clip(ret_w / (vol_384 * math.sqrt(w) + 1e-8), -4.0, 4.0)

    # 3. Каскад EMA
    ema_48 = c.ewm(span=48, adjust=False).mean()
    ema_96 = c.ewm(span=96, adjust=False).mean()
    ema_192 = c.ewm(span=192, adjust=False).mean()
    ema_384 = c.ewm(span=384, adjust=False).mean()
    ema_768 = c.ewm(span=768, adjust=False).mean()
    ema_1536 = c.ewm(span=1536, adjust=False).mean()

    f['dist_ema48'] = np.clip((c - ema_48) / safe_atr96, -6.0, 6.0)
    f['dist_ema96'] = np.clip((c - ema_96) / safe_atr96, -6.0, 6.0)
    f['dist_ema192'] = np.clip((c - ema_192) / safe_atr96, -6.0, 6.0)
    f['dist_ema384'] = np.clip((c - ema_384) / safe_atr96, -6.0, 6.0)
    f['dist_ema768'] = np.clip((c - ema_768) / safe_atr96, -6.0, 6.0)
    f['dist_ema1536'] = np.clip((c - ema_1536) / safe_atr96, -6.0, 6.0)

    f['spread_96_384'] = np.clip((ema_96 - ema_384) / safe_atr96, -6.0, 6.0)
    f['spread_192_768'] = np.clip((ema_192 - ema_768) / safe_atr96, -6.0, 6.0)
    f['spread_384_1536'] = np.clip((ema_384 - ema_1536) / safe_atr96, -6.0, 6.0)

    f['slope_384'] = np.clip((ema_384 - ema_384.shift(32)) / (safe_atr96 * 4.0), -4.0, 4.0)
    f['slope_768'] = np.clip((ema_768 - ema_768.shift(64)) / (safe_atr96 * 6.0), -4.0, 4.0)
    f['slope_1536'] = np.clip((ema_1536 - ema_1536.shift(96)) / (safe_atr96 * 8.0), -4.0, 4.0)

    # 4. Kaufman Efficiency Ratio (KER)
    abs_chg = (c - c.shift(1)).abs()
    for w in [96, 192, 288, 576]:
        net_c = (c - c.shift(w)).abs()
        sum_c = abs_chg.rolling(w).sum().replace(0, np.nan)
        ker_raw = (net_c / sum_c).fillna(0.0)
        f[f'ker_raw_{w}'] = ker_raw
        f[f'signed_ker_{w}'] = np.sign(c - c.shift(w)).fillna(0.0) * ker_raw

    # 5. Канали Дончіана
    for w in [96, 384, 768, 1536]:
        rh = h.rolling(w).max()
        rl = l.rolling(w).min()
        rng = (rh - rl).replace(0, np.nan)
        f[f'donchian_{w}'] = (((c - rl) / rng) * 2.0 - 1.0).fillna(0.0)

    # 6. Осцилятори та Z-Score
    f['rsi_14'] = (_wilder_rsi(c, 14) - 50.0) / 50.0
    f['rsi_64'] = (_wilder_rsi(c, 64) - 50.0) / 50.0
    f['rsi_192'] = (_wilder_rsi(c, 192) - 50.0) / 50.0

    std_96 = c.rolling(96).std().replace(0, np.nan).bfill()
    f['zscore_96'] = np.clip((c - ema_96) / std_96, -4.0, 4.0)

    # 7. Orderflow & Taker Imbalance
    v_ma96 = v.rolling(96).mean().replace(0, np.nan)
    f['vol_surge'] = np.clip((v.rolling(16).mean() / v_ma96).fillna(1.0) - 1.0, -1.0, 3.0)

    if 'taker_base' in df.columns and v.sum() > 0:
        tb = pd.to_numeric(df['taker_base'], errors='coerce').fillna(0.0)
        imb = (tb / v.replace(0, np.nan)) - 0.5
        f['taker_imb_32'] = np.clip(imb.rolling(32).mean() * 4.0, -1.0, 1.0)
        f['taker_imb_96'] = np.clip(imb.rolling(96).mean() * 4.0, -1.0, 1.0)
        f['taker_imb_192'] = np.clip(imb.rolling(192).mean() * 4.0, -1.0, 1.0)
    else:
        f['taker_imb_32'] = 0.0
        f['taker_imb_96'] = 0.0
        f['taker_imb_192'] = 0.0

    feats_df = pd.DataFrame(f, index=df.index).replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0).astype(np.float32)
    feats_df['timestamp'] = df['timestamp'].values
    feats_df['close'] = c.astype(np.float32)
    feats_df['atr'] = atr_14.astype(np.float32)
    return feats_df


def compute_quant_core_signal_and_target(df: pd.DataFrame, bundle: dict,
                                         current_pos_norm: float, bars_held: int,
                                         news_sentiment: float = 0.0) -> tuple[float, float, dict]:
    df_feat = calculate_v7_8_features(df)

    # Обробляємо лише останні 350 барів для миттєвого розрахунку EWM
    tail_df = df_feat.iloc[-350:].reset_index(drop=True)
    feature_names = bundle.get("feature_names", config.FEATURE_COLS)
    X_tail = np.ascontiguousarray(tail_df[feature_names].values, dtype=np.float32)

    # 1. Ансамбль ML (Ridge + LightGBM + CatBoost) в однопотоковому режимі (Zero CPU Overhead)
    scaler = bundle["scaler"]
    ridge = bundle["ridge_model"]
    lgbm = bundle["lgbm_model"]
    cb = bundle["catboost_model"]
    pm = float(bundle.get("pred_mean", 0.0))
    ps = float(bundle.get("pred_std", 1.0))

    X_scaled = np.clip(scaler.transform(X_tail), -4.0, 4.0)
    raw_preds = (
        0.40 * ridge.predict(X_scaled) +
        0.30 * lgbm.predict(X_scaled, n_jobs=1) +
        0.30 * cb.predict(X_scaled, thread_count=1)
    )
    ml_z = np.tanh(((raw_preds - pm) / (ps + 1e-8)) * 0.65)
    sig_ml = pd.Series(ml_z).ewm(span=32, adjust=False).mean().values

    # 2. Структурний TSMOM + EMA Ribbon
    mom_blend = (
        0.10 * tail_df['tsmom_96'].values + 0.20 * tail_df['tsmom_192'].values +
        0.25 * tail_df['tsmom_384'].values + 0.25 * tail_df['tsmom_768'].values +
        0.20 * tail_df['tsmom_1536'].values
    )
    ribbon_blend = (
        0.35 * tail_df['spread_96_384'].values + 0.35 * tail_df['spread_192_768'].values +
        0.30 * tail_df['spread_384_1536'].values
    )
    sig_tsmom = np.tanh(pd.Series(0.55 * mom_blend + 0.45 * ribbon_blend).ewm(span=24, adjust=False).mean().values * 0.85)

    # 3. Векторизований Smart Pullback Dip-Buyer
    macro_bull = (tail_df['spread_192_768'].values > -0.15) & (tail_df['slope_768'].values > -0.10)
    strong_bull = (tail_df['spread_384_1536'].values > 0.10) & (tail_df['tsmom_768'].values > 0.0)
    deep_bear = (tail_df['spread_384_1536'].values < -0.60) & (tail_df['tsmom_768'].values < -0.50) & (tail_df['slope_768'].values < -0.20)

    z96 = tail_df['zscore_96'].values
    rsi14 = tail_df['rsi_14'].values
    donch384 = tail_df['donchian_384'].values
    donch768 = tail_df['donchian_768'].values
    taker96 = tail_df['taker_imb_96'].values
    taker192 = tail_df['taker_imb_192'].values
    ker288 = tail_df['signed_ker_288'].values
    spread_macro = tail_df['spread_384_1536'].values

    dip_boost = np.maximum(0.0, -z96 * 0.35)
    bull_cond = strong_bull | macro_bull
    overheated = (z96 > 2.6) & (rsi14 > 0.55)
    good_struct = (donch384 > -0.25) | (z96 < -0.8)

    bull_val = np.where(overheated, 0.10, np.where(good_struct, np.minimum(1.0, 0.55 + dip_boost), 0.20))
    s_pull = np.where(bull_cond, bull_val, np.where(deep_bear, -0.75, 0.0))
    sig_pullback = pd.Series(s_pull).ewm(span=16, adjust=False).mean().values

    # 4. Ядро V7.8 Ultra (Crash-Shield + Orderflow Boost)
    base_blend = 0.52 * sig_tsmom + 0.48 * sig_pullback
    cascade_dump = (donch384 < -0.85) & (taker96 < -0.15) & (tail_df['tsmom_96'].values < -1.2)

    bo_boost = np.where((donch768 > 0.35) & (ker288 > 0.12), 0.18, 0.0)
    of_boost = np.where((taker192 > 0.08) | (taker96 > 0.12), 0.12, 0.0)
    dip_recovery = np.where((z96 < -0.50) & (spread_macro > 0.0), 0.12, 0.0)

    boosted_long = np.minimum(1.0, base_blend + bo_boost + of_boost + dip_recovery)
    sig_v7_8_raw = np.where(cascade_dump, -0.25, np.where(base_blend > 0.0, boosted_long, 0.0))
    sig_v7_8_ultra = 0.82 * pd.Series(sig_v7_8_raw).ewm(span=16, adjust=False).mean().values + 0.18 * sig_ml

    latest_sig = float(sig_v7_8_ultra[-1])
    is_crash_shield_active = bool(cascade_dump[-1])

    if news_sentiment <= -0.75 and latest_sig > 0:
        latest_sig *= 0.75

    latest_ker = float(tail_df['ker_raw_192'].iloc[-1])
    latest_vr = float(tail_df['vol_ratio_96_384'].iloc[-1])
    latest_z96 = float(tail_df['zscore_96'].iloc[-1])
    latest_price = float(tail_df['close'].iloc[-1])
    latest_atr = float(tail_df['atr'].iloc[-1])

    th = bundle.get("thresholds", {})
    en_l = float(th.get("enter_long_th", config.ENTER_LONG_TH))
    ex_l = float(th.get("exit_long_th", config.EXIT_LONG_TH))
    en_s = float(th.get("enter_short_th", config.ENTER_SHORT_TH))
    ex_s = float(th.get("exit_short_th", config.EXIT_SHORT_TH))
    min_h = int(th.get("min_hold_bars", config.MIN_HOLD_BARS))
    min_ker = float(th.get("min_ker_entry", config.MIN_KER_ENTRY))
    dip_add = bool(th.get("dip_add_active", config.DIP_ADD_ACTIVE))

    tier1_s = float(config.TIER1_SIZE)
    max_conv_s = float(config.MAX_CONVICTION_SIZE)

    desired_pos = current_pos_norm

    if abs(current_pos_norm) < 0.05:
        if latest_sig >= en_l and latest_ker >= min_ker:
            if latest_sig < (en_l + 0.20):
                desired_pos = tier1_s
            else:
                desired_pos = max_conv_s if latest_vr < 1.35 else tier1_s
        elif latest_sig <= -en_s and latest_ker >= min_ker:
            desired_pos = -0.75

    elif current_pos_norm > 0.05:
        is_emergency_crash = (latest_sig <= -0.15) or is_crash_shield_active
        if latest_sig <= -en_s and (bars_held >= min_h or is_emergency_crash):
            desired_pos = -0.75
        elif latest_sig <= ex_l and (bars_held >= min_h or is_emergency_crash):
            desired_pos = 0.0
        else:
            strong_confirm = (latest_sig >= en_l + 0.20)
            smart_dip_buy = dip_add and (latest_sig >= en_l + 0.05) and (latest_z96 < -0.60)
            if current_pos_norm < (max_conv_s - 0.05) and (strong_confirm or smart_dip_buy) and latest_vr < 1.35:
                desired_pos = max_conv_s

    elif current_pos_norm < -0.05:
        if latest_sig >= en_l and bars_held >= min_h:
            desired_pos = tier1_s
        elif latest_sig >= -ex_s and bars_held >= min_h:
            desired_pos = 0.0

    telemetry = {
        "timestamp": str(tail_df['timestamp'].iloc[-1]),
        "price": round(latest_price, 2),
        "atr": round(latest_atr, 2),
        "signal_ultra": round(latest_sig, 4),
        "signal_tsmom": round(float(sig_tsmom[-1]), 4),
        "signal_pullback": round(float(sig_pullback[-1]), 4),
        "signal_ml": round(float(sig_ml[-1]), 4),
        "ker_192": round(latest_ker, 4),
        "vol_ratio": round(latest_vr, 4),
        "zscore_96": round(latest_z96, 4),
        "taker_imb_96": round(float(taker96[-1]), 4),
        "donchian_768": round(float(donch768[-1]), 4),
        "spread_macro": round(float(spread_macro[-1]), 4),
        "crash_shield_active": is_crash_shield_active,
        "news_sentiment": round(float(news_sentiment), 3),
        "enter_long_th": en_l,
        "exit_long_th": ex_l,
        "current_pos_norm": round(float(current_pos_norm), 3),
        "desired_pos": round(float(desired_pos), 3),
        "risk_profile": config.RISK_PROFILE
    }

    return latest_sig, float(desired_pos), telemetry