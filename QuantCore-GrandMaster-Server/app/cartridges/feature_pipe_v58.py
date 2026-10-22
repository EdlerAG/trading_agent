"""
QuantCore V58.0 Pure SOTA Feature Pipeline (2026 Sovereign Edition)
Zero-Fragmentation vector extraction of exactly 55 orthogonal features in Float32.
Designed for sub-50ms real-time execution on 15m Binance Futures candles.
Fully aligned with QuantCore V58 / V53 Quantum Leap production models.
"""
import math
from typing import Dict, Tuple, List
import numpy as np
import pandas as pd


ORTHO_FEATURE_NAMES_V58: List[str] = [
    # --- 20 Base Orthogonal Features ---
    "tsmom_24", "tsmom_96", "tsmom_384", "tsmom_1536",
    "spread_96_384", "spread_384_1536", "slope_768",
    "signed_ker_96", "signed_ker_288", "donchian_96", "donchian_384",
    "zscore_96", "rsi_14", "dist_vwap_96", "vol_surge",
    "taker_imb_32", "taker_imb_96", "btc_lead_24", "rs_vs_btc_96", "rs_vs_btc_384",
    # --- 35 Deep SOTA Tensors ---
    "yz_vol_96", "yz_vol_ratio", "elastic_clock_mom",
    "ehlers_roof_osc", "ehlers_roof_vel", "dist_anchored_vwap",
    "frac_diff_z", "kalman_vel_z", "kalman_acc_z", "kalman_gap_z",
    "whale_ticket_z", "quote_flow_imb_16", "quote_flow_imb_64",
    "vpin_toxicity_z", "hawkes_cascade_z", "dist_vp_poc_96",
    "vp_poc_density", "levy_path_area", "wick_demand_pressure",
    "institutional_absorption", "sortino_asymmetry", "shannon_entropy_96",
    "hurst_vr_ratio", "lead_lag_transfer_z", "dyn_mom_rank",
    "dyn_vol_rank", "trend_quality_score", "funding_rate_z",
    "squeeze_thrust_idx", "cross_dispersion_idx", "cont_breadth_z",
    "geo_shock_idx", "macro_fng_idx", "cs_momentum_z", "cs_orderflow_z",
]


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean().bfill()


def _wilder_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    ema_u = up.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    ema_d = down.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = ema_u / ema_d.replace(0.0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def bi_sym_log_modulus(arr: np.ndarray, scale: float = 3.0, hard_cap: float = 6.0) -> np.ndarray:
    return np.clip(np.sign(arr) * np.log1p(np.abs(arr) * scale), -hard_cap, hard_cap).astype(np.float32)


def compute_yang_zhang_volatility(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, window: int = 96
) -> np.ndarray:
    n = len(c)
    out = np.zeros(n, dtype=np.float32)
    if n < window + 2:
        return out
    k = 0.34 / (1.34 + (window + 1.0) / (window - 1.0))
    log_c = np.log(np.maximum(1e-8, c))
    log_o = np.log(np.maximum(1e-8, o))
    log_h = np.log(np.maximum(1e-8, h))
    log_l = np.log(np.maximum(1e-8, l))

    ret_oc = log_c - log_o
    ret_cc = np.diff(log_c, prepend=log_c[0])
    ret_rs = (log_h - log_c) * (log_h - log_o) + (log_l - log_c) * (log_l - log_o)

    for i in range(window, n):
        sl = slice(i - window + 1, i + 1)
        var_o = float(np.var(ret_cc[sl]))
        var_c = float(np.var(ret_oc[sl]))
        var_rs = float(np.mean(ret_rs[sl]))
        vol_yz = math.sqrt(max(1e-9, var_o + k * var_c + (1.0 - k) * var_rs))
        out[i] = vol_yz
    if window < n:
        out[:window] = out[window]
    return out


def compute_adaptive_kalman(
    log_price: np.ndarray, vol_surge: np.ndarray, hl_range: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(log_price)
    est_pos = np.zeros(n, dtype=np.float32)
    est_vel = np.zeros(n, dtype=np.float32)
    est_acc = np.zeros(n, dtype=np.float32)
    if n == 0:
        return est_pos, est_vel, est_acc

    x_pos = float(log_price[0])
    x_vel = 0.0
    prev_vel = 0.0
    p00, p01, p10, p11 = 1.0, 0.0, 0.0, 1.0
    innov_var = 1e-4

    for i in range(n):
        vs = max(-0.8, min(3.5, float(vol_surge[i])))
        hl = max(1e-5, float(hl_range[i]))
        boost = 1.0 + max(0.0, vs) * 1.45
        q_pos = 1.2e-4 * boost
        q_vel = 2.8e-5 * boost
        r_meas = max(1.2e-3, (7.5e-3 / boost) * (1.0 + 0.22 * (hl / (math.sqrt(innov_var) + 1e-5))))

        p00_p = p00 + p01 + p10 + p11 + q_pos
        p01_p = p01 + p11
        p10_p = p10 + p11
        p11_p = p11 + q_vel

        y_err = float(log_price[i]) - (x_pos + x_vel)
        innov_var = 0.96 * innov_var + 0.04 * (y_err * y_err)
        s_cov = p00_p + r_meas
        k0 = p00_p / s_cov
        k1 = p10_p / s_cov

        x_pos = (x_pos + x_vel) + k0 * y_err
        x_vel = x_vel + k1 * y_err
        p00 = (1.0 - k0) * p00_p
        p01 = (1.0 - k0) * p01_p
        p10 = -k1 * p00_p + p10_p
        p11 = -k1 * p01_p + p11_p

        est_pos[i] = x_pos
        est_vel[i] = x_vel
        est_acc[i] = x_vel - prev_vel
        prev_vel = x_vel

    return est_pos, est_vel, est_acc


def compute_ehlers_roofing_filter(c: np.ndarray, atr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    n = len(c)
    roof_osc = np.zeros(n, dtype=np.float32)
    roof_vel = np.zeros(n, dtype=np.float32)
    if n < 4:
        return roof_osc, roof_vel

    a1 = math.exp(-1.414 * math.pi / 16.0)
    b1 = 2.0 * a1 * math.cos(1.414 * math.pi / 16.0)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3

    hp = np.zeros(n, dtype=np.float64)
    cos_rad = math.cos(0.707 * 2.0 * math.pi / 96.0)
    sin_rad = math.sin(0.707 * 2.0 * math.pi / 96.0)
    alpha_hp = (cos_rad + sin_rad - 1.0) / max(1e-6, cos_rad)

    for i in range(2, n):
        c0, c1_p, c2_p = float(c[i]), float(c[i - 1]), float(c[i - 2])
        a_val = max(c0 * 0.0015, float(atr[i]))
        hp[i] = (
            ((1.0 - alpha_hp / 2.0) ** 2) * (c0 - 2.0 * c1_p + c2_p)
            + 2.0 * (1.0 - alpha_hp) * hp[i - 1]
            - ((1.0 - alpha_hp) ** 2) * hp[i - 2]
        )
        filt = c1 * (hp[i] + hp[i - 1]) * 0.5 + c2 * roof_osc[i - 1] * a_val + c3 * roof_osc[i - 2] * a_val
        roof_osc[i] = np.clip(filt / a_val, -4.5, 4.5)
        roof_vel[i] = roof_osc[i] - roof_osc[i - 1]

    return roof_osc, roof_vel


def compute_anchored_vwap_dist(
    c: np.ndarray, h: np.ndarray, l: np.ndarray, qv: np.ndarray, vsurge: np.ndarray, atr: np.ndarray
) -> np.ndarray:
    n = len(c)
    dist = np.zeros(n, dtype=np.float32)
    cum_pv, cum_v = 0.0, 0.0
    bars = 0
    for i in range(n):
        typ_p = 0.5 * (float(c[i]) + 0.5 * (float(h[i]) + float(l[i])))
        q = max(1.0, float(qv[i]))
        a = max(float(c[i]) * 0.0015, float(atr[i]))
        is_climax = (float(vsurge[i]) > 1.35 and bars >= 16)
        if bars >= 96 or is_climax or i == 0:
            cum_pv = typ_p * q
            cum_v = q
            bars = 1
        else:
            cum_pv = 0.985 * cum_pv + typ_p * q
            cum_v = 0.985 * cum_v + q
            bars += 1
        avwap = cum_pv / max(1.0, cum_v)
        dist[i] = np.clip((float(c[i]) - avwap) / a, -5.5, 5.5)
    return dist


def compute_elastic_clock_momentum(
    c: np.ndarray, yz_vol: np.ndarray, vsurge: np.ndarray
) -> np.ndarray:
    n = len(c)
    out = np.zeros(n, dtype=np.float32)
    valid_vol = yz_vol[yz_vol > 0]
    med_vol = float(np.median(valid_vol)) if len(valid_vol) > 0 else 0.0035
    if med_vol <= 1e-6:
        med_vol = 0.0035
    for i in range(16, n):
        rel_int = (float(yz_vol[i]) / med_vol) * (1.0 + 0.30 * max(0.0, float(vsurge[i])))
        lb = int(96.0 / max(0.55, min(4.2, rel_int)))
        lb = max(18, min(176, lb))
        idx_past = max(0, i - lb)
        ret_dyn = math.log(max(1e-8, float(c[i])) / max(1e-8, float(c[idx_past])))
        denom = float(yz_vol[i]) * math.sqrt(float(lb)) + 1e-8
        out[i] = np.clip(ret_dyn / denom, -4.5, 4.5)
    return out


def compute_frac_diff_z(log_p: np.ndarray, d: float = 0.35, window: int = 64) -> np.ndarray:
    n = len(log_p)
    w = np.empty(window, dtype=np.float64)
    w[0] = 1.0
    for k in range(1, window):
        w[k] = -w[k - 1] * ((d - float(k) + 1.0) / float(k))
    fd_raw = np.convolve(log_p, w[::-1], mode="full")[:n]
    fd_raw[:window] = 0.0
    fd_ser = pd.Series(fd_raw)
    rolling_m = fd_ser.rolling(384, min_periods=32).mean()
    rolling_s = fd_ser.rolling(384, min_periods=32).std().replace(0, np.nan).bfill() + 1e-8
    fd_z = (fd_ser - rolling_m) / rolling_s
    return bi_sym_log_modulus(fd_z.fillna(0.0).values, scale=2.5, hard_cap=5.0)


def compute_rolling_poc_features(
    c: np.ndarray, h: np.ndarray, l: np.ndarray, qv: np.ndarray, atr: np.ndarray, window: int = 96
) -> Tuple[np.ndarray, np.ndarray]:
    n = len(c)
    dist_poc = np.zeros(n, dtype=np.float32)
    poc_dens = np.zeros(n, dtype=np.float32)
    n_bins = 12
    step = 2
    for i in range(window, n, step):
        sl = slice(i - window + 1, i + 1)
        c_sub = c[sl]
        h_sub = h[sl]
        l_sub = l[sl]
        qv_sub = qv[sl]
        mn = np.min(l_sub)
        mx = np.max(h_sub)
        span = mx - mn
        if span < 1e-8:
            poc_price = c[i]
            dens = 0.0
        else:
            typ = 0.5 * (c_sub + 0.5 * (h_sub + l_sub))
            bin_idx = np.clip(((typ - mn) / span * n_bins).astype(int), 0, n_bins - 1)
            b_vols = np.bincount(bin_idx, weights=qv_sub, minlength=n_bins)
            best_b = int(np.argmax(b_vols))
            poc_price = mn + (float(best_b) + 0.5) * (span / float(n_bins))
            tot_v = float(np.sum(b_vols))
            dens = (b_vols[best_b] / (tot_v + 1e-8) * float(n_bins)) - 1.0

        a = max(float(c[i]) * 0.0015, float(atr[i]))
        d_val = (float(c[i]) - poc_price) / a
        dist_poc[i] = d_val
        poc_dens[i] = dens
        if i + 1 < n:
            dist_poc[i + 1] = d_val
            poc_dens[i + 1] = dens
    if window < n:
        dist_poc[:window] = dist_poc[window]
        poc_dens[:window] = poc_dens[window]
    return dist_poc, poc_dens


def compute_levy_area(norm_p_chg: np.ndarray, norm_oflow: np.ndarray, window: int = 32) -> np.ndarray:
    n = len(norm_p_chg)
    out = np.zeros(n, dtype=np.float32)
    for i in range(window, n):
        sl = slice(i - window + 1, i + 1)
        dx = norm_p_chg[sl]
        dy = norm_oflow[sl]
        x_p = np.cumsum(dx)
        y_f = np.cumsum(dy)
        area = 0.5 * np.sum(x_p * dy - y_f * dx)
        out[i] = area / float(window)
    return out


def compute_shannon_entropy(ret_arr: np.ndarray, window: int = 96) -> np.ndarray:
    n = len(ret_arr)
    out = np.full(n, 0.75, dtype=np.float32)
    n_bins = 8
    log_max = math.log(float(n_bins))
    step = 2
    for i in range(window, n, step):
        sub = ret_arr[i - window:i]
        mn, mx = np.min(sub), np.max(sub)
        span = mx - mn
        if span < 1e-9:
            out[i] = 0.5
            if i + 1 < n:
                out[i + 1] = 0.5
            continue
        bin_idx = np.clip(((sub - mn) / span * n_bins).astype(int), 0, n_bins - 1)
        counts = np.bincount(bin_idx, minlength=n_bins)
        p = counts[counts > 0] / float(window)
        ent = -np.sum(p * np.log(p)) / log_max
        out[i] = ent
        if i + 1 < n:
            out[i + 1] = ent
    if window < n:
        out[:window] = out[window]
    return out


def compute_core_breadth_and_macro(
    candles_map: Dict[str, pd.DataFrame],
    anchor_symbols: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"),
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Computes BTC reference close, core breadth, continuous breadth thrust z-score,
    cross-asset dispersion, and geo-macro shock detector.
    """
    btc_df = candles_map["BTCUSDT"] if "BTCUSDT" in candles_map else next(iter(candles_map.values()))
    btc_close = btc_df["close"].astype(float).reset_index(drop=True)
    n = len(btc_close)

    above_ema = np.zeros(n, dtype=np.float32)
    valid_cnt = 0
    mom_stack = []

    for s in anchor_symbols:
        df_s = candles_map.get(s)
        if df_s is None or len(df_s) < 100:
            continue
        c_s = df_s["close"].astype(float).iloc[-n:].reset_index(drop=True)
        if len(c_s) == n:
            ema_192 = c_s.ewm(span=192, adjust=False).mean()
            above_ema += (c_s.values > ema_192.values).astype(np.float32)
            mom_stack.append(c_s.pct_change(24).fillna(0.0).values)
            valid_cnt += 1

    if valid_cnt == 0:
        valid_cnt = 1
        above_ema = (btc_close.values > btc_close.ewm(span=192, adjust=False).mean().values).astype(np.float32)
        mom_stack.append(btc_close.pct_change(24).fillna(0.0).values)

    core_breadth = pd.Series((above_ema / float(valid_cnt)) * 2.0 - 1.0, dtype=np.float32)
    thrust_raw = pd.Series(core_breadth).ewm(span=16, adjust=False).mean()
    cont_breadth_z = pd.Series(np.clip(thrust_raw.values * 1.5, -2.5, 2.5), dtype=np.float32)

    # Geo-Macro Shock: simultaneous sharp breakdown across all anchors
    if mom_stack:
        anchor_mom_mean = np.mean(mom_stack, axis=0)
        geo_shock = pd.Series(np.clip(-anchor_mom_mean / 0.025, -3.0, 3.0), dtype=np.float32)
    else:
        geo_shock = pd.Series(np.zeros(n, dtype=np.float32))

    # Cross-Asset Dispersion
    if len(mom_stack) >= 2:
        disp_raw = np.std(mom_stack, axis=0)
        cross_disp = pd.Series(np.clip((disp_raw - 0.015) / 0.010, -2.0, 3.0), dtype=np.float32)
    else:
        cross_disp = pd.Series(np.zeros(n, dtype=np.float32))

    return btc_close, core_breadth, cont_breadth_z, cross_disp, geo_shock


def compute_v58_features_float32(
    df: pd.DataFrame,
    btc_close: pd.Series,
    eth_close: pd.Series,
    core_breadth: pd.Series,
    cont_breadth_z: pd.Series,
    cross_disp: pd.Series,
    geo_shock: pd.Series,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Computes all 55 SOTA orthogonal features for a single coin in pure Float32.
    Returns: (ortho_features_df, atr_14_series).
    """
    n = len(df)
    c = df["close"].astype(float).reset_index(drop=True)
    h = df["high"].astype(float).reset_index(drop=True)
    l = df["low"].astype(float).reset_index(drop=True)
    o = df["open"].astype(float).reset_index(drop=True) if "open" in df.columns else c.copy()
    v = df["volume"].astype(float).reset_index(drop=True)

    # Volume & Orderflow
    tb = df["taker_base"].astype(float).reset_index(drop=True) if "taker_base" in df.columns else (v * 0.5)
    qv = df["quote_volume"].astype(float).reset_index(drop=True) if "quote_volume" in df.columns else (c * v)
    tq = df["taker_quote"].astype(float).reset_index(drop=True) if "taker_quote" in df.columns else (c * tb)
    fr = df["funding_rate"].astype(float).reset_index(drop=True) if "funding_rate" in df.columns else pd.Series(np.full(n, 0.0001, dtype=np.float32))

    o_np = o.values
    h_np = h.values
    l_np = l.values
    c_np = c.values
    qv_np = qv.values
    tq_np = tq.values

    # 1. Volatility
    atr_14 = _wilder_atr(h, l, c, 14)
    atr_96 = _wilder_atr(h, l, c, 96)
    safe_atr96 = atr_96.replace(0, np.nan).bfill()

    yz_vol_96 = compute_yang_zhang_volatility(o_np, h_np, l_np, c_np, 96)
    yz_vol_384 = compute_yang_zhang_volatility(o_np, h_np, l_np, c_np, 384)
    safe_vol384 = pd.Series(yz_vol_384).replace(0, np.nan).bfill().values

    vol_surge = (v / (v.rolling(96, min_periods=16).mean() + 1e-8) - 1.0).fillna(0.0)

    # 2. Time-Series Momentum
    f = {}
    for w in (24, 96, 384, 1536):
        ret_w = np.log(c / c.shift(w)).fillna(0.0)
        f[f"tsmom_{w}"] = bi_sym_log_modulus((ret_w / (safe_vol384 * math.sqrt(w) + 1e-8)).values, scale=2.8, hard_cap=4.5)

    # 3. EMA Spreads & Slopes
    ema_96 = c.ewm(span=96, adjust=False).mean()
    ema_384 = c.ewm(span=384, adjust=False).mean()
    ema_768 = c.ewm(span=768, adjust=False).mean()
    ema_1536 = c.ewm(span=1536, adjust=False).mean()

    f["spread_96_384"] = bi_sym_log_modulus(((ema_96 - ema_384) / safe_atr96).values, scale=3.2, hard_cap=6.0)
    f["spread_384_1536"] = bi_sym_log_modulus(((ema_384 - ema_1536) / safe_atr96).values, scale=3.2, hard_cap=6.0)
    f["slope_768"] = bi_sym_log_modulus(((ema_768 - ema_768.shift(64)) / (safe_atr96 * 6.0)).fillna(0.0).values, scale=2.5, hard_cap=4.0)

    # 4. Kaufman Efficiency Ratio (KER)
    abs_chg = (c - c.shift(1)).abs()
    for w in (96, 288):
        net_c = (c - c.shift(w)).abs()
        sum_c = abs_chg.rolling(w, min_periods=16).sum().replace(0, np.nan)
        ker_raw = (net_c / sum_c).fillna(0.0)
        f[f"signed_ker_{w}"] = np.sign(c - c.shift(w)).fillna(0.0).values * ker_raw.values

    # 5. Donchian Channels
    for w in (96, 384):
        rh = h.rolling(w, min_periods=16).max()
        rl = l.rolling(w, min_periods=16).min()
        rng = (rh - rl).replace(0, np.nan)
        f[f"donchian_{w}"] = (((c - rl) / rng) * 2.0 - 1.0).fillna(0.0).values

    # 6. Z-Score, RSI, VWAP, Vol Surge
    std_96 = c.rolling(96, min_periods=16).std().replace(0, np.nan).bfill()
    f["zscore_96"] = np.clip((c - ema_96) / std_96, -4.0, 4.0).fillna(0.0).values
    f["rsi_14"] = ((_wilder_rsi(c, 14) - 50.0) / 25.0).fillna(0.0).values

    cum_vol_96 = v.rolling(96, min_periods=16).sum().replace(0, np.nan)
    cum_pv_96 = (c * v).rolling(96, min_periods=16).sum()
    vwap_96 = cum_pv_96 / cum_vol_96
    f["dist_vwap_96"] = np.clip((c - vwap_96) / safe_atr96, -4.5, 4.5).fillna(0.0).values
    f["vol_surge"] = np.clip(vol_surge.values, -1.0, 5.0)

    # 7. Taker Orderflow Imbalance
    for w in (32, 96):
        t_buy = tb.rolling(w, min_periods=8).sum()
        t_tot = v.rolling(w, min_periods=8).sum().replace(0, np.nan)
        f[f"taker_imb_{w}"] = np.clip((2.0 * (t_buy / t_tot) - 1.0).fillna(0.0), -1.0, 1.0).values

    # 8. Lead-Lag & Relative Strength vs BTC
    if len(btc_close) >= n:
        btc_c = btc_close.iloc[-n:].reset_index(drop=True)
    else:
        btc_c = c.copy()

    f["btc_lead_24"] = np.clip((c.pct_change(24) - btc_c.pct_change(24)).fillna(0.0) / 0.035, -3.0, 3.0).values
    for w in (96, 384):
        rs_w = np.log(c / c.shift(w)).fillna(0.0) - np.log(btc_c / btc_c.shift(w)).fillna(0.0)
        f[f"rs_vs_btc_{w}"] = bi_sym_log_modulus((rs_w / (safe_vol384 * math.sqrt(w) + 1e-8)).values, scale=2.5, hard_cap=4.0)

    # --- 35 Deep SOTA Tensors ---
    f["yz_vol_96"] = yz_vol_96
    f["yz_vol_ratio"] = bi_sym_log_modulus(yz_vol_96 / (safe_vol384 + 1e-8), scale=2.0, hard_cap=4.5)
    f["elastic_clock_mom"] = compute_elastic_clock_momentum(c_np, yz_vol_96, f["vol_surge"])

    e_osc, e_vel = compute_ehlers_roofing_filter(c_np, safe_atr96.values)
    f["ehlers_roof_osc"] = e_osc
    f["ehlers_roof_vel"] = e_vel

    f["dist_anchored_vwap"] = compute_anchored_vwap_dist(c_np, h_np, l_np, qv_np, f["vol_surge"], safe_atr96.values)

    log_p = np.log(np.maximum(1e-8, c_np))
    f["frac_diff_z"] = compute_frac_diff_z(log_p, d=0.35, window=64)

    hl_rel = ((h - l) / c.replace(0, np.nan)).fillna(0.002).values
    k_pos, k_vel, k_acc = compute_adaptive_kalman(log_p, f["vol_surge"], hl_rel)
    v_norm = yz_vol_96 + 1e-6
    f["kalman_vel_z"] = bi_sym_log_modulus(k_vel / v_norm, scale=2.5, hard_cap=5.0)
    f["kalman_acc_z"] = bi_sym_log_modulus(pd.Series(k_acc / v_norm).ewm(span=10, adjust=False).mean().values * 5.0, scale=2.5, hard_cap=5.0)
    f["kalman_gap_z"] = bi_sym_log_modulus((log_p - k_pos) / (v_norm * 2.0), scale=2.5, hard_cap=5.0)

    # Whale ticket & Quote flow imbalance
    nt_proxy = v / np.maximum(1e-5, safe_atr96.values * 0.1)
    avg_ticket = qv / pd.Series(nt_proxy).replace(0, np.nan)
    ticket_ma = avg_ticket.rolling(192, min_periods=16).mean().replace(0, np.nan).bfill()
    ticket_std = avg_ticket.rolling(192, min_periods=16).std().replace(0, np.nan).bfill() + 1e-8
    f["whale_ticket_z"] = bi_sym_log_modulus(
        ((avg_ticket - ticket_ma) / ticket_std).ewm(span=12, adjust=False).mean().fillna(0.0).values,
        scale=2.5, hard_cap=5.0
    )

    net_taker_usd = (2.0 * tq - qv) / qv.replace(0, np.nan)
    f["quote_flow_imb_16"] = bi_sym_log_modulus(net_taker_usd.ewm(span=16, adjust=False).mean().fillna(0.0).values * 4.0, scale=2.0, hard_cap=4.0)
    f["quote_flow_imb_64"] = bi_sym_log_modulus(net_taker_usd.ewm(span=64, adjust=False).mean().fillna(0.0).values * 4.0, scale=2.0, hard_cap=4.0)

    # VPIN & Hawkes
    vpin_raw = (tq - (qv - tq)).abs().rolling(48, min_periods=8).sum() / (qv.rolling(48, min_periods=8).sum() + 1e-8)
    vpin_m = vpin_raw.rolling(384, min_periods=32).mean()
    vpin_s = vpin_raw.rolling(384, min_periods=32).std().replace(0, np.nan).bfill() + 1e-8
    vpin_z = (vpin_raw - vpin_m) / vpin_s
    f["vpin_toxicity_z"] = bi_sym_log_modulus(vpin_z.fillna(0.0).values, scale=2.5, hard_cap=4.5)
    f["hawkes_cascade_z"] = bi_sym_log_modulus(vpin_raw.ewm(span=16, adjust=False).mean().fillna(0.0).values * 2.0, scale=2.5, hard_cap=5.0)

    # Volume Profile POC
    dist_poc, poc_dens = compute_rolling_poc_features(c_np, h_np, l_np, qv_np, safe_atr96.values, 96)
    f["dist_vp_poc_96"] = bi_sym_log_modulus(dist_poc, scale=2.5, hard_cap=5.5)
    f["vp_poc_density"] = np.clip(poc_dens, -1.0, 4.0)

    norm_p_chg = (c.diff().fillna(0.0) / safe_atr96).values
    norm_oflow = f["quote_flow_imb_16"]
    f["levy_path_area"] = bi_sym_log_modulus(compute_levy_area(norm_p_chg, norm_oflow, 32), scale=2.0, hard_cap=4.5)

    # Wick demand pressure & institutional absorption
    candle_rng = (h - l).replace(0, np.nan)
    lower_wick = (np.minimum(o, c) - l) / candle_rng
    upper_wick = (h - np.maximum(o, c)) / candle_rng
    f["wick_demand_pressure"] = bi_sym_log_modulus(((lower_wick - upper_wick).fillna(0.0).ewm(span=20, adjust=False).mean() * 3.0).values, scale=2.0, hard_cap=4.0)

    rel_qv = (qv / qv.rolling(96, min_periods=16).mean().replace(0, np.nan)).fillna(1.0)
    rel_tr = ((h - l) / safe_atr96).replace(0, 0.1)
    f["institutional_absorption"] = bi_sym_log_modulus(((rel_qv / (rel_tr + 0.30)).ewm(span=16, adjust=False).mean() - 1.0).values, scale=2.0, hard_cap=4.5)

    # Sortino & Shannon
    log_ret = np.log(c / c.shift(1)).fillna(0.0)
    up_r = log_ret.clip(lower=0.0)
    dn_r = (-log_ret.clip(upper=0.0))
    up_semi = np.sqrt((up_r ** 2).ewm(span=96, adjust=False).mean() + 1e-10)
    dn_semi = np.sqrt((dn_r ** 2).ewm(span=96, adjust=False).mean() + 1e-10)
    f["sortino_asymmetry"] = bi_sym_log_modulus(((up_semi / dn_semi) - 1.0).values, scale=1.8, hard_cap=3.5)
    f["shannon_entropy_96"] = compute_shannon_entropy(log_ret.values, 96)

    # Hurst VR
    ret_32 = np.log(c / c.shift(32)).fillna(0.0)
    ret_4 = np.log(c / c.shift(4)).fillna(0.0)
    f["hurst_vr_ratio"] = np.clip((ret_32.rolling(128, min_periods=16).std() / (ret_4.rolling(128, min_periods=16).std() * math.sqrt(8) + 1e-9)).fillna(1.0).values, 0.45, 1.75)

    # Lead-Lag Transfer BTC/ETH
    btc_vol = np.log(btc_c / btc_c.shift(1)).rolling(384, min_periods=16).std().replace(0, np.nan).bfill()
    btc_fast_imp = np.log(btc_c / btc_c.shift(8)).fillna(0.0) / (btc_vol * math.sqrt(8) + 1e-8)
    if len(eth_close) >= n:
        eth_c = eth_close.iloc[-n:].reset_index(drop=True)
    else:
        eth_c = btc_c.copy()
    eth_vol = np.log(eth_c / eth_c.shift(1)).rolling(384, min_periods=16).std().replace(0, np.nan).bfill()
    eth_fast_imp = np.log(eth_c / eth_c.shift(8)).fillna(0.0) / (eth_vol * math.sqrt(8) + 1e-8)
    coin_fast_imp = np.log(c / c.shift(8)).fillna(0.0) / (safe_vol384 * math.sqrt(8) + 1e-8)
    lead_lag_gap = (0.55 * btc_fast_imp + 0.45 * eth_fast_imp) - 0.65 * coin_fast_imp
    f["lead_lag_transfer_z"] = bi_sym_log_modulus(lead_lag_gap.ewm(span=6, adjust=False).mean().fillna(0.0).values, scale=2.2, hard_cap=4.0)

    # Dynamic quantile ranks
    mom_comp = pd.Series(0.50 * f["tsmom_96"] + 0.50 * f["tsmom_384"])
    f["dyn_mom_rank"] = (mom_comp.rolling(768, min_periods=32).rank(pct=True).fillna(0.5).values * 2.0 - 1.0).astype(np.float32)
    f["dyn_vol_rank"] = pd.Series(yz_vol_96).rolling(768, min_periods=32).rank(pct=True).fillna(0.5).values.astype(np.float32)

    f["trend_quality_score"] = np.clip(
        0.40 * f["sortino_asymmetry"] + 0.35 * f["signed_ker_288"] + 0.25 * f["rs_vs_btc_96"],
        -2.5, 2.5
    ).astype(np.float32)

    # Funding & Macro indices
    f["funding_rate_z"] = bi_sym_log_modulus(((fr - 0.0001) / 0.00025).values, scale=2.5, hard_cap=5.0)
    f["squeeze_thrust_idx"] = np.clip(f["tsmom_24"] * 0.7 + f["taker_imb_32"] * 0.5, -3.0, 3.0).astype(np.float32)
    f["cross_dispersion_idx"] = cross_disp.iloc[-n:].values.astype(np.float32) if len(cross_disp) >= n else np.zeros(n, dtype=np.float32)
    f["cont_breadth_z"] = cont_breadth_z.iloc[-n:].values.astype(np.float32) if len(cont_breadth_z) >= n else np.zeros(n, dtype=np.float32)
    f["geo_shock_idx"] = geo_shock.iloc[-n:].values.astype(np.float32) if len(geo_shock) >= n else np.zeros(n, dtype=np.float32)
    f["macro_fng_idx"] = np.zeros(n, dtype=np.float32)

    # CS Momentum & CS Orderflow (local approximation for standalone asset, updated in cross-sectional pass)
    f["cs_momentum_z"] = np.tanh(f["tsmom_96"] * 0.5 + f["kalman_vel_z"] * 0.3).astype(np.float32)
    f["cs_orderflow_z"] = np.tanh(f["taker_imb_96"] + f["hawkes_cascade_z"] * 0.4).astype(np.float32)

    # Ensure canonical column order of exactly 55 features
    df_out = pd.DataFrame(f, index=df.index)[ORTHO_FEATURE_NAMES_V58].replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0).astype(np.float32)
    return df_out, atr_14
