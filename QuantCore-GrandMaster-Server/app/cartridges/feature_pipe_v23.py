import math
from typing import Dict, Tuple
import numpy as np
import pandas as pd


FEATURE_COLS_V23: Tuple[str, ...] = (
    "vol_96", "vol_ratio_96_384",
    "tsmom_24", "tsmom_48", "tsmom_96", "tsmom_192", "tsmom_384", "tsmom_768", "tsmom_1536",
    "dist_ema48", "dist_ema96", "dist_ema192", "dist_ema384", "dist_ema768", "dist_ema1536",
    "spread_96_384", "spread_192_768", "spread_384_1536",
    "slope_384", "slope_768", "slope_1536",
    "ker_raw_96", "signed_ker_96", "ker_raw_192", "signed_ker_192",
    "ker_raw_288", "signed_ker_288", "ker_raw_576", "signed_ker_576",
    "donchian_96", "donchian_384", "donchian_768", "donchian_1536",
    "zscore_64", "zscore_96",
    "rsi_14", "rsi_64", "rsi_192",
    "dist_vwap_96", "vol_surge",
    "taker_imb_32", "taker_imb_96", "taker_imb_192",
    "btc_lead_24", "btc_lead_96",
    "rs_vs_btc_96", "rs_vs_btc_384", "market_breadth",
)


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


def compute_core_market_breadth(
    candles_map: Dict[str, pd.DataFrame],
    anchor_symbols: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"),
) -> Tuple[pd.Series, pd.Series]:
    """
    Обчислює еталонний ряд закриття BTC та системну ширину ринку (core_breadth)
    виключно за якірними мейджорами, захищаючи сигнали від шуму сателітів.
    """
    btc_df = candles_map.get("BTCUSDT") or next(iter(candles_map.values()))
    btc_close = btc_df["close"].astype(float).reset_index(drop=True)
    n_len = len(btc_close)

    above_ema = np.zeros(n_len, dtype=np.float32)
    valid_anchors = 0

    for sym in anchor_symbols:
        df_s = candles_map.get(sym)
        if df_s is None or len(df_s) < 200:
            continue
        c_s = df_s["close"].astype(float).iloc[-n_len:].reset_index(drop=True)
        if len(c_s) == n_len:
            ema_192 = c_s.ewm(span=192, adjust=False).mean()
            above_ema += (c_s.values > ema_192.values).astype(np.float32)
            valid_anchors += 1

    if valid_anchors == 0:
        ema_192 = btc_close.ewm(span=192, adjust=False).mean()
        above_ema = (btc_close.values > ema_192.values).astype(np.float32)
        valid_anchors = 1

    core_breadth = pd.Series((above_ema / float(valid_anchors)) * 2.0 - 1.0, dtype=np.float32)
    return btc_close, core_breadth


def compute_v23_features_float32(
    df: pd.DataFrame,
    btc_close: pd.Series,
    core_breadth: pd.Series,
) -> pd.DataFrame:
    """
    Zero-Fragmentation розрахунок 43 факторів V23 Grand-Master у форматі float32.
    Виконує всі векторні операції за один прохід у словнику пам'яті.
    """
    n = len(df)
    c = df["close"].astype(float).reset_index(drop=True)
    h = df["high"].astype(float).reset_index(drop=True)
    l = df["low"].astype(float).reset_index(drop=True)
    v = df["volume"].astype(float).reset_index(drop=True)

    if len(btc_close) >= n:
        btc_c = btc_close.iloc[-n:].reset_index(drop=True)
        mb_s = core_breadth.iloc[-n:].reset_index(drop=True)
    else:
        btc_c = c.copy()
        mb_s = pd.Series(np.zeros(n, dtype=np.float32))

    f = {}
    log_ret = np.log(c / c.shift(1)).fillna(0.0)
    vol_96 = log_ret.rolling(96).std().replace(0, np.nan).bfill()
    vol_384 = log_ret.rolling(384).std().replace(0, np.nan).bfill()

    atr_14 = _wilder_atr(h, l, c, 14)
    atr_96 = _wilder_atr(h, l, c, 96)
    safe_atr96 = atr_96.replace(0, np.nan).bfill()

    f["vol_96"] = vol_96
    f["vol_ratio_96_384"] = np.clip((vol_96 / vol_384).fillna(1.0), 0.30, 3.0)

    for w in (24, 48, 96, 192, 384, 768, 1536):
        ret_w = np.log(c / c.shift(w)).fillna(0.0)
        f[f"tsmom_{w}"] = np.clip(ret_w / (vol_384 * math.sqrt(w) + 1e-8), -4.5, 4.5)

    ema_48 = c.ewm(span=48, adjust=False).mean()
    ema_96 = c.ewm(span=96, adjust=False).mean()
    ema_192 = c.ewm(span=192, adjust=False).mean()
    ema_384 = c.ewm(span=384, adjust=False).mean()
    ema_768 = c.ewm(span=768, adjust=False).mean()
    ema_1536 = c.ewm(span=1536, adjust=False).mean()

    f["dist_ema48"] = np.clip((c - ema_48) / safe_atr96, -6.0, 6.0)
    f["dist_ema96"] = np.clip((c - ema_96) / safe_atr96, -6.0, 6.0)
    f["dist_ema192"] = np.clip((c - ema_192) / safe_atr96, -6.0, 6.0)
    f["dist_ema384"] = np.clip((c - ema_384) / safe_atr96, -6.0, 6.0)
    f["dist_ema768"] = np.clip((c - ema_768) / safe_atr96, -6.0, 6.0)
    f["dist_ema1536"] = np.clip((c - ema_1536) / safe_atr96, -6.0, 6.0)

    f["spread_96_384"] = np.clip((ema_96 - ema_384) / safe_atr96, -6.0, 6.0)
    f["spread_192_768"] = np.clip((ema_192 - ema_768) / safe_atr96, -6.0, 6.0)
    f["spread_384_1536"] = np.clip((ema_384 - ema_1536) / safe_atr96, -6.0, 6.0)

    f["slope_384"] = np.clip((ema_384 - ema_384.shift(32)) / (safe_atr96 * 4.0), -4.0, 4.0)
    f["slope_768"] = np.clip((ema_768 - ema_768.shift(64)) / (safe_atr96 * 6.0), -4.0, 4.0)
    f["slope_1536"] = np.clip((ema_1536 - ema_1536.shift(96)) / (safe_atr96 * 8.0), -4.0, 4.0)

    abs_chg = (c - c.shift(1)).abs()
    for w in (96, 192, 288, 576):
        net_c = (c - c.shift(w)).abs()
        sum_c = abs_chg.rolling(w).sum().replace(0, np.nan)
        ker_raw = (net_c / sum_c).fillna(0.0)
        f[f"ker_raw_{w}"] = ker_raw
        f[f"signed_ker_{w}"] = np.sign(c - c.shift(w)).fillna(0.0) * ker_raw

    for w in (96, 384, 768, 1536):
        rh = h.rolling(w).max()
        rl = l.rolling(w).min()
        rng = (rh - rl).replace(0, np.nan)
        f[f"donchian_{w}"] = (((c - rl) / rng) * 2.0 - 1.0).fillna(0.0)

    std_64 = c.rolling(64).std().replace(0, np.nan).bfill()
    std_96 = c.rolling(96).std().replace(0, np.nan).bfill()
    f["zscore_64"] = np.clip((c - c.ewm(span=64, adjust=False).mean()) / std_64, -4.0, 4.0)
    f["zscore_96"] = np.clip((c - ema_96) / std_96, -4.0, 4.0)

    f["rsi_14"] = (_wilder_rsi(c, 14) - 50.0) / 50.0
    f["rsi_64"] = (_wilder_rsi(c, 64) - 50.0) / 50.0
    f["rsi_192"] = (_wilder_rsi(c, 192) - 50.0) / 50.0

    pv = c * v
    vwap_96 = (pv.rolling(96).sum() / v.rolling(96).sum().replace(0, np.nan)).bfill()
    f["dist_vwap_96"] = np.clip((c - vwap_96) / safe_atr96, -5.0, 5.0)

    v_ma96 = v.rolling(96).mean().replace(0, np.nan)
    f["vol_surge"] = np.clip((v.rolling(16).mean() / v_ma96).fillna(1.0) - 1.0, -1.0, 3.0)

    if "taker_base" in df.columns and v.sum() > 0:
        tb = pd.to_numeric(df["taker_base"], errors="coerce").fillna(0.0).reset_index(drop=True)
        imb = (tb / v.replace(0, np.nan)) - 0.5
        f["taker_imb_32"] = np.clip(imb.rolling(32).mean() * 4.0, -1.0, 1.0)
        f["taker_imb_96"] = np.clip(imb.rolling(96).mean() * 4.0, -1.0, 1.0)
        f["taker_imb_192"] = np.clip(imb.rolling(192).mean() * 4.0, -1.0, 1.0)
    else:
        for w in (32, 96, 192):
            f[f"taker_imb_{w}"] = 0.0

    btc_vol = np.log(btc_c / btc_c.shift(1)).rolling(384).std().replace(0, np.nan).bfill()
    f["btc_lead_24"] = np.clip(np.log(btc_c / btc_c.shift(24)).fillna(0.0) / (btc_vol * math.sqrt(24) + 1e-8), -4.0, 4.0)
    f["btc_lead_96"] = np.clip(np.log(btc_c / btc_c.shift(96)).fillna(0.0) / (btc_vol * math.sqrt(96) + 1e-8), -4.0, 4.0)

    rs_ratio = (c / btc_c.replace(0, np.nan)).bfill()
    rs_vol = np.log(rs_ratio / rs_ratio.shift(1)).rolling(384).std().replace(0, np.nan).bfill().fillna(1e-4)
    f["rs_vs_btc_96"] = np.clip(np.log(rs_ratio / rs_ratio.shift(96)).fillna(0.0) / (rs_vol * math.sqrt(96) + 1e-8), -4.0, 4.0)
    f["rs_vs_btc_384"] = np.clip(np.log(rs_ratio / rs_ratio.shift(384)).fillna(0.0) / (rs_vol * math.sqrt(384) + 1e-8), -4.0, 4.0)
    f["market_breadth"] = mb_s.values

    feats_df = pd.DataFrame(f).replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0).astype(np.float32)
    feats_df["close"] = c.astype(np.float32)
    feats_df["atr"] = atr_14.astype(np.float32)
    if "timestamp" in df.columns:
        feats_df["timestamp"] = df["timestamp"].values
    return feats_df