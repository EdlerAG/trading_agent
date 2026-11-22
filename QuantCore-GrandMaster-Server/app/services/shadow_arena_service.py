# -*- coding: utf-8 -*-
"""Shadow Arena Service — живий чемпіонат 6 актуальних конфігурацій QuantCore V5.0 All-Regime (нуль застарілих версій!).

Працює з НУЛЬОВИМ додатковим трафіком до біржі (< 3 MB RAM, < 15 мс CPU на годину):
  * Використовує спільний 49-факторний Numba-куб і 37-фічевий Dual-Horizon ML ансамбль;
  * Погодинно виконує точний живий супровід Chandelier + Breakeven + MFE Take-Profit (+2.6 ATR) для кожного бота:
      1) V5.0_Sov_500       ($500  — основне ядро V5.0 All-Regime Sovereign, двійник реального рахунку $500)
      2) V5.0_Sov_2000      ($2000 — професійний тір V5.0)
      3) V5.0_Sov_10000     ($10k  — інституційний тір V5.0)
      4) V5.0_Turbo_500     ($500  — сміливий Overdrive-профіль)
      5) V5.0_FastSwing_500 ($500  — фокус на швидких 24h-ML свінгах і часткових тейках MFE у боковику)
      6) V4.0_Prev_500      ($500  — попередній еталон V4.0 Apex для прямого живого A/B контролю)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import numpy as np
import orjson
import pandas as pd

from app.core.config import settings
from app.domain.interfaces import IService
from app.services.database_service import DatabaseService

for _cand_root in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]):
    if (_cand_root / "quant_v2").is_dir() and str(_cand_root) not in sys.path:
        sys.path.insert(0, str(_cand_root))

try:
    from quant_v2.allocator import compute_portfolio_vol_metric
    from quant_v2.config import (
        DEFAULT_CONFIG,
        V40_PREV_CONFIG,
        V5_FASTSWING_CONFIG,
        V5_OVERDRIVE_CONFIG,
    )
    from quant_v2.features import compute_features, panel_from_candles
    from quant_v2.live import (
        LiveState,
        _get_live_dual_ml_scores_last_bar,
        _step_live_c_stops_and_mfe,
        _sync_c_meta_after_rebalance,
    )
    from quant_v2.sleeves import compute_live_weights, round_qty_to_lot, update_tier2, update_tier3
    _V5_OK = True
except Exception:
    _V5_OK = False


class ShadowArenaService(IService):
    """Інституційний полігон одночасного порівняння 6 актуальних профілів V5.0 проти попереднього V4.0."""

    __slots__ = ("_logger", "_db", "_state_path", "_bots", "_last_ts")

    BOT_SPECS = (
        ("V5.0_Sov_500",       "V5.0 All-Regime Sovereign ($500)", 500.0,   "v5_base"),
        ("V5.0_Sov_2000",      "V5.0 All-Regime Pro ($2,000)",     2000.0,  "v5_base"),
        ("V5.0_Sov_10000",     "V5.0 Institutional ($10k)",        10000.0, "v5_base"),
        ("V5.0_Turbo_500",     "V5.0 Overdrive Bold ($500)",       500.0,   "v5_turbo"),
        ("V5.0_FastSwing_500", "V5.0 Fast 24h-ML + MFE ($500)",    500.0,   "v5_fast"),
        ("V4.0_Prev_500",      "V4.0 Попередня База ($500)",       500.0,   "v4_prev"),
    )

    def __init__(self, logger: logging.Logger, db_service: DatabaseService, state_path: Optional[str] = None) -> None:
        self._logger = logger
        self._db = db_service
        self._state_path = state_path or os.path.join(settings.STORAGE_DIR, "shadow_arena_state.json")
        self._bots: Dict[str, Dict[str, Any]] = {}
        self._last_ts: str = ""
        self._init_default_bots()

    @property
    def name(self) -> str:
        return "ShadowArenaService"

    def _init_default_bots(self) -> None:
        for bot_id, label, init_eq, kind in self.BOT_SPECS:
            if bot_id not in self._bots:
                self._bots[bot_id] = {
                    "bot_id": bot_id,
                    "label": label,
                    "kind": kind,
                    "initial_equity": float(init_eq),
                    "cash": float(init_eq),
                    "peak_equity": float(init_eq),
                    "max_dd_pct": 0.0,
                    "fees_usd": 0.0,
                    "funding_usd": 0.0,
                    "trades_count": 0,
                    "last_funding_bucket": -1,
                    "positions": {},
                    "live_state": {},
                    "latest_equity": float(init_eq),
                    "latest_gross": 0.0,
                    "latest_net": 0.0,
                }

    async def init(self) -> None:
        self._load_state()

    async def shutdown(self) -> None:
        self._save_state()

    def _load_state(self) -> None:
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, "rb") as f:
                data = orjson.loads(f.read())
            self._last_ts = str(data.get("last_ts") or "")
            saved_bots = data.get("bots") or {}
            for bid, bdict in saved_bots.items():
                if bid in self._bots and isinstance(bdict, dict):
                    self._bots[bid].update(bdict)
        except Exception as e:
            self._logger.debug(f"[ShadowArena] Load state skipped: {e}")

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            tmp = self._state_path + ".tmp"
            payload = {"last_ts": self._last_ts, "bots": self._bots}
            with open(tmp, "wb") as f:
                f.write(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY))
            os.replace(tmp, self._state_path)
        except Exception:
            pass

    @staticmethod
    def _mark_equity(bot: Dict[str, Any], prices: Mapping[str, float]) -> float:
        eq = float(bot["cash"])
        for sym, pos in bot["positions"].items():
            qty = float(pos.get("qty", 0.0))
            ep = float(pos.get("entry_px", 0.0))
            cp = float(prices.get(sym, ep) or ep)
            if abs(qty) > 1e-12 and cp > 0:
                eq += qty * (cp - ep)
        return max(0.0, float(eq))

    @staticmethod
    def _apply_funding_if_due(
        bot: Dict[str, Any],
        bar_ts_ms: int,
        prices: Mapping[str, float],
        funding_rates: Mapping[str, float],
    ) -> None:
        bar_h = int(bar_ts_ms // 3_600_000)
        if bar_h % 4 != 0 or bar_h == int(bot.get("last_funding_bucket", -1)):
            return
        # На 8h монетах фандінг 00/08/16 UTC; на 4h монетах — кожні 4h
        is_8h_mark = (bar_h % 8 == 0)
        bot["last_funding_bucket"] = bar_h
        for sym, pos in bot["positions"].items():
            qty = float(pos.get("qty", 0.0))
            if abs(qty) <= 1e-12:
                continue
            if not is_8h_mark:
                continue
            rate = float(funding_rates.get(sym, 0.0) or 0.0)
            px = float(prices.get(sym, 0.0) or 0.0)
            if abs(rate) > 1e-12 and px > 0:
                cost = qty * px * rate
                bot["cash"] = float(bot["cash"]) - cost
                bot["funding_usd"] = float(bot["funding_usd"]) + cost

    @staticmethod
    def _rebalance_virtual_book(
        bot: Dict[str, Any],
        target_weights: Mapping[str, float],
        prices: Mapping[str, float],
        spread_bps_map: Optional[Mapping[str, float]] = None,
        rel_tol: float = 0.22,
    ) -> None:
        eq = ShadowArenaService._mark_equity(bot, prices)
        if eq <= 1.0:
            return
        positions: Dict[str, Dict[str, float]] = bot["positions"]
        min_delta_usd = max(5.0, 0.015 * eq)
        base_fee = 0.00020 * 0.70 + 0.00050 * 0.30

        all_syms = set(positions.keys()) | set(target_weights.keys())
        for sym in all_syms:
            px = float(prices.get(sym, 0.0) or 0.0)
            if px <= 0 or not np.isfinite(px):
                continue
            w = float(target_weights.get(sym, 0.0) or 0.0)
            cur_rec = positions.get(sym)
            cur_qty = float(cur_rec["qty"]) if cur_rec else 0.0
            cur_ep = float(cur_rec["entry_px"]) if cur_rec else px

            if abs(w) < 0.012:
                q_tgt = 0.0
            else:
                q_tgt = round_qty_to_lot(w * eq / px, px, sym) if _V5_OK else round(w * eq / px, 4)

            delta = q_tgt - cur_qty
            is_close = (abs(q_tgt) < 1e-12) and (abs(cur_qty) > 1e-12)
            if (not is_close) and abs(delta) * px < max(min_delta_usd, rel_tol * abs(cur_qty) * px):
                continue
            if abs(delta) < 1e-12:
                continue

            if abs(cur_qty) > 1e-12:
                if abs(q_tgt) < 1e-12 or (cur_qty * q_tgt) < 0.0:
                    bot["cash"] = float(bot["cash"]) + (px - cur_ep) * cur_qty
                    bot["trades_count"] = int(bot["trades_count"]) + 1
                    new_ep = px
                elif abs(q_tgt) < abs(cur_qty):
                    closed = abs(cur_qty) - abs(q_tgt)
                    sgn = 1.0 if cur_qty > 0 else -1.0
                    bot["cash"] = float(bot["cash"]) + (px - cur_ep) * closed * sgn
                    bot["trades_count"] = int(bot["trades_count"]) + 1
                    new_ep = cur_ep
                else:
                    add_q = abs(q_tgt) - abs(cur_qty)
                    new_ep = (abs(cur_qty) * cur_ep + add_q * px) / max(abs(q_tgt), 1e-12)
            else:
                new_ep = px

            notional = abs(delta) * px
            sp_half = 0.00005 if sym in ("BTCUSDT", "ETHUSDT") else 0.00015
            if spread_bps_map and sym in spread_bps_map and float(spread_bps_map[sym]) > 0:
                sp_half = 0.5 * float(spread_bps_map[sym]) / 10_000.0
            fee_usd = notional * (base_fee + sp_half)
            bot["cash"] = float(bot["cash"]) - fee_usd
            bot["fees_usd"] = float(bot["fees_usd"]) + fee_usd

            if abs(q_tgt) > 1e-12:
                positions[sym] = {"qty": float(q_tgt), "entry_px": float(new_ep)}
            else:
                positions.pop(sym, None)

    def step_all(
        self,
        candle_ts: str,
        candles_map: Dict[str, pd.DataFrame],
        prices: Mapping[str, float],
        funding_rates: Mapping[str, float],
        coin_news_bias: Optional[Mapping[str, float]] = None,
        spread_bps_map: Optional[Mapping[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        if not settings.ENABLE_SHADOW_ARENA or not candles_map:
            return self.get_leaderboard()
        if candle_ts == self._last_ts:
            return self.get_leaderboard()

        self._last_ts = str(candle_ts)
        ref_df = candles_map.get("BTCUSDT", next(iter(candles_map.values())))
        bar_ts_ms = int(ref_df["open_ms"].iloc[-1]) if "open_ms" in ref_df.columns else int(pd.Timestamp(candle_ts).value // 10 ** 6)

        for bot in self._bots.values():
            self._apply_funding_if_due(bot, bar_ts_ms, prices, funding_rates)

        if _V5_OK:
            try:
                all_syms = tuple(s for s in candles_map.keys())
                panel = panel_from_candles(candles_map, symbols=all_syms)
                feat = compute_features(panel)
                t = len(panel["ts"]) - 1
                syms_l = [str(s) for s in panel["symbols"]]
                if t >= 10:
                    ml_168, ml_24 = _get_live_dual_ml_scores_last_bar(
                        feat, panel["valid"], DEFAULT_CONFIG.sleeve_b.ml_blend_weight, True
                    )
                    cfg_map = {
                        "v5_base": DEFAULT_CONFIG,
                        "v5_turbo": V5_OVERDRIVE_CONFIG,
                        "v5_fast": V5_FASTSWING_CONFIG,
                        "v4_prev": V40_PREV_CONFIG,
                    }

                    for _bid, bot in self._bots.items():
                        use_cfg = cfg_map.get(bot["kind"], DEFAULT_CONFIG)
                        st = LiveState.from_dict(bot.get("live_state") or {})
                        eq_now = self._mark_equity(bot, prices)
                        if st.initial_equity <= 0:
                            st.initial_equity = float(bot["initial_equity"])
                        st.peak_equity = max(float(st.peak_equity), eq_now)

                        cur_bar_ms = int(panel["ts"][t])
                        if cur_bar_ms != st.last_ts_ms and eq_now > 0:
                            st.recent_eq_history.append(float(eq_now))
                            if len(st.recent_eq_history) > 169:
                                st.recent_eq_history = st.recent_eq_history[-169:]
                        st.last_ts_ms = cur_bar_ms

                        has_v3_u = ("oi_usd" in panel) and bool(np.isfinite(panel["oi_usd"][t]).any())
                        seed_unl = bool(has_v3_u and getattr(use_cfg.allocator, "v3_seed_unlock", False))
                        st.tier2_active = True if seed_unl else update_tier2(eq_now, st.tier2_active, use_cfg.allocator)
                        st.tier3_active = True if seed_unl else update_tier3(eq_now, st.tier3_active, use_cfg.allocator)

                        active_c_pos, c_hit = (
                            _step_live_c_stops_and_mfe(st, panel, feat, t, syms_l, use_cfg) if has_v3_u else ({}, False)
                        )

                        cont_1h_u = bool(has_v3_u and getattr(use_cfg.sleeve_b, "continuous_1h_ewma", False))
                        n_tr_u = 1 if cont_1h_u else (max(1, int(getattr(use_cfg.sleeve_b, "n_tranches", 1))) if has_v3_u else 1)
                        stride_b_u = 1 if cont_1h_u else max(1, int(use_cfg.sleeve_b.rebalance_every_h) // n_tr_u)
                        bar_h = cur_bar_ms // 3_600_000
                        b_bkt = bar_h // stride_b_u
                        c_bkt = bar_h if cont_1h_u else (bar_h // max(1, use_cfg.sleeve_c.rebalance_every_h))
                        d_bkt = bar_h if cont_1h_u else (bar_h // max(1, use_cfg.sleeve_d.rebalance_every_h))
                        b_due = b_bkt != st.last_b_bucket
                        c_due = bool(has_v3_u and use_cfg.sleeve_c.enabled and st.tier2_active and c_bkt != st.last_c_bucket)
                        d_due = bool(has_v3_u and use_cfg.sleeve_d.enabled and st.tier3_active and d_bkt != st.last_d_bucket)

                        if b_due or c_due or d_due or c_hit:
                            p_rv = (
                                compute_portfolio_vol_metric(
                                    np.asarray(st.recent_eq_history, dtype=np.float64),
                                    use_downside=bool(getattr(use_cfg.risk, "use_downside_vol", False)),
                                )
                                if (has_v3_u and len(st.recent_eq_history) >= 96 and not getattr(use_cfg.risk, "use_ex_ante_lw_vol", False))
                                else None
                            )
                            init_tr_u = st.b_tranches if st.b_tranches else [dict(st.last_b_weights) for _ in range(n_tr_u)]
                            net_w, a_w, b_w, c_w, d_w, _rm, new_tr_u = compute_live_weights(
                                feat, panel, t, eq_now, {}, st.last_a_weights, st.last_b_weights, st.peak_equity,
                                use_cfg.sleeve_a, use_cfg.sleeve_b, use_cfg.risk, use_cfg.allocator,
                                funding_filter=True, tier2_active=st.tier2_active, force_b_rebalance=b_due,
                                initial_equity=st.initial_equity, ml_scores_t=ml_168, ml_fast_scores_t=ml_24,
                                cfg_c=use_cfg.sleeve_c, cfg_d=use_cfg.sleeve_d,
                                last_c_weights=st.last_c_weights, last_d_weights=st.last_d_weights,
                                tier3_active=st.tier3_active, force_c_rebalance=c_due,
                                coin_news_bias=coin_news_bias, port_rvol_ann=p_rv,
                                active_c_positions=active_c_pos, b_tranches=init_tr_u,
                                return_all_sleeves=True, return_tranches=True,
                            )
                            if b_due:
                                st.last_b_weights, st.last_a_weights = dict(b_w), dict(a_w)
                                st.b_tranches = [dict(x) for x in new_tr_u] if n_tr_u > 1 else []
                                st.last_b_bucket = b_bkt
                            if d_due or b_due:
                                st.last_d_weights = dict(d_w)
                                st.last_d_bucket = d_bkt
                            if c_due or b_due:
                                st.last_c_weights = dict(c_w)
                                if c_due:
                                    st.last_c_bucket = c_bkt
                                if has_v3_u:
                                    _sync_c_meta_after_rebalance(st, st.last_c_weights, panel, feat, t, syms_l, use_cfg)
                            bot["live_state"] = st.to_dict()
                            self._rebalance_virtual_book(bot, net_w, prices, spread_bps_map, rel_tol=use_cfg.sleeve_b.rebalance_rel_tol)
                        else:
                            bot["live_state"] = st.to_dict()
            except Exception as e:
                self._logger.debug(f"[ShadowArena] V5 eval skipped: {e}")

        snap_rows: List[Dict[str, Any]] = []
        for bot in self._bots.values():
            eq_f = self._mark_equity(bot, prices)
            bot["latest_equity"] = eq_f
            bot["peak_equity"] = max(float(bot["peak_equity"]), eq_f)
            dd_now = 100.0 * (eq_f / max(float(bot["peak_equity"]), 1e-9) - 1.0)
            bot["max_dd_pct"] = min(float(bot["max_dd_pct"]), dd_now)

            g_lev = 0.0
            n_lev = 0.0
            if eq_f > 0:
                for s, p in bot["positions"].items():
                    q = float(p.get("qty", 0.0))
                    px = float(prices.get(s, p.get("entry_px", 0.0)) or 0.0)
                    w_i = (q * px) / eq_f
                    g_lev += abs(w_i)
                    n_lev += w_i
            bot["latest_gross"] = round(g_lev, 3)
            bot["latest_net"] = round(n_lev, 3)
            ret_pct = 100.0 * (eq_f / max(float(bot["initial_equity"]), 1.0) - 1.0)
            snap_rows.append({
                "bot_id": bot["bot_id"],
                "equity": round(eq_f, 2),
                "return_pct": round(ret_pct, 3),
                "max_dd_pct": round(float(bot["max_dd_pct"]), 3),
                "gross_lev": round(g_lev, 3),
                "net_lev": round(n_lev, 3),
                "trades_count": int(bot["trades_count"]),
                "fees_usd": round(float(bot["fees_usd"]), 3),
                "funding_usd": round(float(bot["funding_usd"]), 3),
            })

        self._save_state()
        if hasattr(self._db, "record_shadow_arena_batch"):
            try:
                self._db.record_shadow_arena_batch(candle_ts, snap_rows)
            except Exception:
                pass
        return self.get_leaderboard()

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for bot in self._bots.values():
            init_eq = max(float(bot["initial_equity"]), 1.0)
            cur_eq = float(bot.get("latest_equity", init_eq))
            ret_pct = 100.0 * (cur_eq / init_eq - 1.0)
            rows.append({
                "bot_id": bot["bot_id"],
                "label": bot["label"],
                "initial_equity": round(init_eq, 2),
                "equity": round(cur_eq, 2),
                "return_pct": round(ret_pct, 2),
                "max_dd_pct": round(float(bot.get("max_dd_pct", 0.0)), 2),
                "gross_lev": round(float(bot.get("latest_gross", 0.0)), 2),
                "net_lev": round(float(bot.get("latest_net", 0.0)), 2),
                "active_positions": len(bot.get("positions") or {}),
                "trades_count": int(bot.get("trades_count", 0)),
                "fees_usd": round(float(bot.get("fees_usd", 0.0)), 2),
                "funding_usd": round(float(bot.get("funding_usd", 0.0)), 2),
            })
        rows.sort(key=lambda r: r["return_pct"], reverse=True)
        for idx, r in enumerate(rows, 1):
            r["rank"] = idx
        return rows
