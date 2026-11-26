# -*- coding: utf-8 -*-
"""Єдине математичне ядро розрахунку метрик ефективності, Equity Bridge та Rolling Live IC.

Використовується одночасно у веб-API (`DatabaseService.get_equity_series_and_kpis`)
та в інституційному CLI-аудиті (`scripts/audit_report.py`), усуваючи будь-які розбіжності формул.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
import pandas as pd
from scipy import stats


def compute_unified_performance_metrics(
    timestamps: Sequence[Any],
    equities: Sequence[float],
    trade_pnls: Optional[Sequence[float]] = None,
    provisional_min_days: float = 14.0,
) -> Dict[str, Any]:
    """Уніфікований розрахунок дохідності, MaxDD, Sharpe (provisional <14d), Sortino, Calmar, WinRate і Profit Factor."""
    if len(equities) < 2:
        init_v = float(equities[0]) if len(equities) == 1 else 0.0
        return {
            "start_equity": round(init_v, 2),
            "latest_equity": round(init_v, 2),
            "total_pnl_usd": 0.0,
            "total_pnl_pct": 0.0,
            "days_elapsed": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sharpe_hourly_ann": 0.0,
            "sharpe_non_annualized": 0.0,
            "sharpe_is_provisional": True,
            "sharpe_label": "provisional (0.0d)",
            "sortino_ratio": 0.0,
            "sortino_non_annualized": 0.0,
            "calmar_ratio": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
        }

    ts_idx = pd.to_datetime(list(timestamps), utc=True, errors="coerce")
    s_raw = pd.Series(np.asarray(equities, dtype=np.float64), index=ts_idx)
    s_raw = s_raw[s_raw.index.notna() & np.isfinite(s_raw.values) & (s_raw.values > 0.0)].sort_index()
    if len(s_raw) < 2:
        return {
            "start_equity": 0.0,
            "latest_equity": 0.0,
            "total_pnl_usd": 0.0,
            "total_pnl_pct": 0.0,
            "days_elapsed": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sharpe_hourly_ann": 0.0,
            "sharpe_non_annualized": 0.0,
            "sharpe_is_provisional": True,
            "sharpe_label": "provisional (0.0d)",
            "sortino_ratio": 0.0,
            "sortino_non_annualized": 0.0,
            "calmar_ratio": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
        }

    # Агрегуємо до чистих 1h закриттів та UTC-денних закриттів (без дублів рестартів усередині години)
    s_1h = s_raw.resample("1h").last().dropna()
    if len(s_1h) < 2:
        s_1h = s_raw
    s_1d = s_raw.resample("1D").last().dropna()

    init_eq = float(s_raw.iloc[0])
    last_eq = float(s_raw.iloc[-1])
    pnl_usd = last_eq - init_eq
    pnl_pct = (last_eq / max(init_eq, 1e-9) - 1.0) * 100.0
    days_elapsed = max(0.0, (s_raw.index[-1] - s_raw.index[0]).total_seconds() / 86400.0)

    peaks = np.maximum.accumulate(s_raw.values)
    dd_series = (s_raw.values - peaks) / np.maximum(peaks, 1e-9) * 100.0
    max_dd_pct = float(np.min(dd_series))

    rets_1h = s_1h.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    rets_1d = s_1d.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

    # Неануалізований Sharpe/Sortino на годинних барах (чесний показник для коротких вікон <14 діб)
    if len(rets_1h) >= 3 and float(rets_1h.std()) > 1e-12:
        mu_h = float(rets_1h.mean())
        sd_h = float(rets_1h.std())
        sr_non_ann = mu_h / sd_h
        sr_1h_ann = sr_non_ann * float(np.sqrt(8760.0))
        down_h = rets_1h[rets_1h < 0.0]
        dd_sd_h = float(np.sqrt(np.mean(np.square(down_h.values)))) if len(down_h) > 0 else sd_h
        sortino_non_ann = mu_h / max(dd_sd_h, 1e-12)
        sortino_1h_ann = sortino_non_ann * float(np.sqrt(8760.0))
    else:
        sr_non_ann = 0.0
        sr_1h_ann = 0.0
        sortino_non_ann = 0.0
        sortino_1h_ann = 0.0

    # Канонічний денний Sharpe (коли є >= 4 повних UTC-днів переходів), інакше обережна 1h оцінка з позначкою provisional
    if len(rets_1d) >= 4 and float(rets_1d.std()) > 1e-12:
        sr_daily_ann = float(rets_1d.mean() / rets_1d.std() * np.sqrt(365.0))
        down_d = rets_1d[rets_1d < 0.0]
        dd_sd_d = float(np.sqrt(np.mean(np.square(down_d.values)))) if len(down_d) > 0 else float(rets_1d.std())
        sortino_ann = float(rets_1d.mean() / max(dd_sd_d, 1e-12) * np.sqrt(365.0))
    else:
        sr_daily_ann = sr_1h_ann
        sortino_ann = sortino_1h_ann

    is_prov = bool(days_elapsed < provisional_min_days)
    # На дуже коротких вікнах (<14d) обмежуємо відображуваний provisional Sharpe розумним діапазоном [-10, +10] проти шуму 2-3 днів
    disp_sr = float(np.clip(sr_daily_ann, -10.0, 10.0)) if is_prov else float(sr_daily_ann)
    disp_sortino = float(np.clip(sortino_ann, -15.0, 15.0)) if is_prov else float(sortino_ann)

    calmar = float(pnl_pct / max(abs(max_dd_pct), 0.50)) if not is_prov else float(pnl_pct / max(abs(max_dd_pct), 1.0))

    # Win rate & Profit Factor: за закритими угодами (якщо передані ненульові PnL) або за годинними ретернами
    pnls_clean = [float(x) for x in (trade_pnls or []) if np.isfinite(float(x)) and abs(float(x)) > 1e-9]
    if pnls_clean:
        wins = [x for x in pnls_clean if x > 0.0]
        losses = [abs(x) for x in pnls_clean if x < 0.0]
        win_rate = 100.0 * len(wins) / len(pnls_clean)
        pf = (sum(wins) / sum(losses)) if sum(losses) > 1e-9 else (99.0 if wins else 0.0)
    elif len(rets_1h) > 0:
        wins_h = rets_1h[rets_1h > 0.0]
        loss_h = rets_1h[rets_1h < 0.0].abs()
        nz_cnt = int((rets_1h.abs() > 1e-9).sum())
        win_rate = (100.0 * len(wins_h) / nz_cnt) if nz_cnt > 0 else 0.0
        pf = float(wins_h.sum() / loss_h.sum()) if float(loss_h.sum()) > 1e-12 else 0.0
    else:
        win_rate = 0.0
        pf = 0.0

    sr_lbl = f"{disp_sr:.2f} (provisional {days_elapsed:.1f}d)" if is_prov else f"{disp_sr:.2f}"
    return {
        "start_equity": round(init_eq, 2),
        "latest_equity": round(last_eq, 2),
        "total_pnl_usd": round(pnl_usd, 4),
        "total_pnl_pct": round(pnl_pct, 3),
        "days_elapsed": round(days_elapsed, 2),
        "max_drawdown_pct": round(max_dd_pct, 3),
        "sharpe_ratio": round(disp_sr, 2),
        "sharpe_hourly_ann": round(sr_1h_ann, 2),
        "sharpe_non_annualized": round(sr_non_ann, 4),
        "sharpe_is_provisional": is_prov,
        "sharpe_label": sr_lbl,
        "sortino_ratio": round(disp_sortino, 2),
        "sortino_non_annualized": round(sortino_non_ann, 4),
        "calmar_ratio": round(calmar, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(min(pf, 99.99), 2),
    }


def compute_equity_bridge_dict(
    start_equity: float,
    actual_equity: float,
    realized_pnl_gross: float,
    delta_unrealized_pnl: float,
    net_funding_usd: float,
    total_fees_usd: float,
    drift_warn_usd: float = 0.05,
) -> Dict[str, Any]:
    """Перевіряє фундаментальну бухгалтерську тотожність рахунку:
    expected_equity = start_equity + realized_pnl_gross + delta_unrealized_pnl + net_funding_usd - total_fees_usd.
    """
    exp_eq = (
        float(start_equity)
        + float(realized_pnl_gross)
        + float(delta_unrealized_pnl)
        + float(net_funding_usd)
        - abs(float(total_fees_usd))
    )
    diff = float(actual_equity) - exp_eq
    return {
        "start_equity": round(float(start_equity), 4),
        "realized_pnl_usd": round(float(realized_pnl_gross), 4),
        "unrealized_pnl_delta_usd": round(float(delta_unrealized_pnl), 4),
        "net_funding_usd": round(float(net_funding_usd), 4),
        "total_fees_usd": round(abs(float(total_fees_usd)), 4),
        "expected_equity": round(exp_eq, 4),
        "actual_equity": round(float(actual_equity), 4),
        "accounting_diff_usd": round(diff, 4),
        "within_tolerance": bool(abs(diff) <= drift_warn_usd),
    }


def compute_hourly_attribution_step(
    prev_equity: float,
    prev_weights_a: Mapping[str, float],
    prev_weights_b: Mapping[str, float],
    prev_weights_c: Mapping[str, float],
    prev_weights_d: Mapping[str, float],
    prev_factors: Mapping[str, Mapping[str, float]],
    prev_prices: Mapping[str, float],
    curr_prices: Mapping[str, float],
    prev_weights_net: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """Декомпозує годинну дохідність портфеля на внесок кожного рукава (A, B, C, D) та альфа-фактора.

    Якщо передано фінальні масштабовані ваги `prev_weights_net` (з урахуванням overlay_scale,
    портфельного vol-target та фактично закритих стопів), ваги рукавів на кожній монеті
    узгоджуються так, щоб `wa_eff + wb_eff + wc_eff + wd_eff == weights_net[sym]`.
    """
    eq = max(float(prev_equity), 0.0)
    sl_a = sl_b = sl_c = sl_d = 0.0
    fac_pnl = {
        "z_mom": 0.0,
        "z_carry": 0.0,
        "z_bab": 0.0,
        "z_flow": 0.0,
        "z_spot": 0.0,
        "z_smart_oi": 0.0,
    }
    # Ваги стовпів V6.1 з quant_v2/config.py (для пропорційної декомпозиції вкладу Sleeve B)
    pillar_w = {
        "z_mom": 0.22,
        "z_carry": 0.18,
        "z_bab": 0.20,
        "z_flow": 0.16,
        "z_spot": 0.10,
        "z_smart_oi": 0.14,
    }
    has_net = prev_weights_net is not None and len(prev_weights_net) > 0

    all_syms = set(prev_prices.keys()) & set(curr_prices.keys())
    for sym in all_syms:
        p0 = float(prev_prices.get(sym, 0.0) or 0.0)
        p1 = float(curr_prices.get(sym, 0.0) or 0.0)
        if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and p1 > 0):
            continue
        r_bar = (p1 / p0) - 1.0
        if abs(r_bar) > 0.80:
            continue

        wa = float(prev_weights_a.get(sym, 0.0) or 0.0)
        wb = float(prev_weights_b.get(sym, 0.0) or 0.0)
        wc = float(prev_weights_c.get(sym, 0.0) or 0.0)
        wd = float(prev_weights_d.get(sym, 0.0) or 0.0)

        if has_net and prev_weights_net is not None:
            wn = float(prev_weights_net.get(sym, 0.0) or 0.0)
            raw_sum = wa + wb + wc + wd
            if abs(wn) < 1e-7:
                wa = wb = wc = wd = 0.0
            elif abs(raw_sum) > 1e-7 and (raw_sum * wn) > 0.0:
                sc = wn / raw_sum
                wa *= sc
                wb *= sc
                wc *= sc
                wd *= sc
            else:
                abs_tot = abs(wa) + abs(wb) + abs(wc) + abs(wd)
                if abs_tot > 1e-7:
                    # Протилежне перекриття рукавів -> розподіляємо залишок пропорційно модулям із збереженням суми wn
                    diff_w = wn - raw_sum
                    wa += diff_w * (abs(wa) / abs_tot)
                    wb += diff_w * (abs(wb) / abs_tot)
                    wc += diff_w * (abs(wc) / abs_tot)
                    wd += diff_w * (abs(wd) / abs_tot)
                elif sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"):
                    wa, wb, wc, wd = wn, 0.0, 0.0, 0.0
                else:
                    wa, wb, wc, wd = 0.0, wn, 0.0, 0.0

        sl_a += wa * eq * r_bar
        pnl_b_sym = wb * eq * r_bar
        sl_b += pnl_b_sym
        sl_c += wc * eq * r_bar
        sl_d += wd * eq * r_bar

        f_map = prev_factors.get(sym) or {}
        if abs(wb) > 1e-6 and f_map:
            # Атрибутуємо pnl_b_sym пропорційно знаковому внеску факторів у напрямок позиції wb
            sgn_b = 1.0 if wb > 0 else -1.0
            contrib_raw = {
                fk: max(0.0, sgn_b * float(f_map.get(fk, 0.0) or 0.0) * fw)
                for fk, fw in pillar_w.items()
            }
            tot_c = sum(contrib_raw.values())
            if tot_c > 1e-9:
                for fk, cv in contrib_raw.items():
                    fac_pnl[fk] += pnl_b_sym * (cv / tot_c)
            else:
                for fk, fw in pillar_w.items():
                    fac_pnl[fk] += pnl_b_sym * fw

    tot_port_ret = (sl_a + sl_b + sl_c + sl_d) / max(eq, 1e-9) if eq > 0 else 0.0
    return {
        "port_ret_1h": round(float(tot_port_ret), 6),
        "sleeve_a_pnl": round(sl_a, 5),
        "sleeve_b_pnl": round(sl_b, 5),
        "sleeve_c_pnl": round(sl_c, 5),
        "sleeve_d_pnl": round(sl_d, 5),
        "fac_mom_pnl": round(fac_pnl["z_mom"], 5),
        "fac_carry_pnl": round(fac_pnl["z_carry"], 5),
        "fac_bab_pnl": round(fac_pnl["z_bab"], 5),
        "fac_flow_pnl": round(fac_pnl["z_flow"], 5),
        "fac_spot_pnl": round(fac_pnl["z_spot"], 5),
        "fac_smart_oi_pnl": round(fac_pnl["z_smart_oi"], 5),
    }


def compute_rolling_spearman_ic(
    decisions: Sequence[Mapping[str, Any]],
    horizons_h: Tuple[int, ...] = (1, 4, 24),
) -> Dict[str, Dict[str, float]]:
    """Обчислює фактичний живий Spearman Rank IC між z_factor[i, t] та forward return r[i, t -> t+H] для H in (1h, 4h, 24h)."""
    factor_keys = ("score", "z_mom", "z_carry", "z_bab", "z_flow", "z_spot", "z_smart_oi")
    ts_to_dec: Dict[int, Mapping[str, Any]] = {}
    for d in decisions:
        cms = int(d.get("candle_ms") or 0)
        if cms > 0 and d.get("prices") and d.get("factors"):
            ts_to_dec[cms] = d

    sorted_ts = sorted(ts_to_dec.keys())
    out: Dict[str, Dict[str, float]] = {fk: {} for fk in factor_keys}

    for h in horizons_h:
        h_ms = int(h) * 3_600_000
        ic_lists: Dict[str, List[float]] = {fk: [] for fk in factor_keys}
        for t0 in sorted_ts:
            t1 = t0 + h_ms
            if t1 not in ts_to_dec:
                continue
            d0 = ts_to_dec[t0]
            d1 = ts_to_dec[t1]
            p0_map = d0["prices"]
            p1_map = d1["prices"]
            f0_map = d0["factors"]
            common_syms = [
                s for s in f0_map.keys()
                if s in p0_map and s in p1_map and float(p0_map[s] or 0) > 0 and float(p1_map[s] or 0) > 0
            ]
            if len(common_syms) < 8:
                continue
            fwd_rets = np.asarray([float(p1_map[s]) / float(p0_map[s]) - 1.0 for s in common_syms], dtype=np.float64)
            if float(np.std(fwd_rets)) < 1e-12:
                continue
            for fk in factor_keys:
                f_vals = np.asarray([float((f0_map[s] or {}).get(fk, np.nan)) for s in common_syms], dtype=np.float64)
                mask = np.isfinite(f_vals) & np.isfinite(fwd_rets)
                if int(mask.sum()) >= 8 and float(np.std(f_vals[mask])) > 1e-12:
                    ic_res = stats.spearmanr(f_vals[mask], fwd_rets[mask]).statistic
                    if np.isfinite(ic_res):
                        ic_lists[fk].append(float(ic_res))

        for fk in factor_keys:
            vals = ic_lists[fk]
            out[fk][f"ic_{h}h"] = round(float(np.mean(vals)), 4) if vals else 0.0
            out[fk][f"n_{h}h"] = len(vals)
    return out
