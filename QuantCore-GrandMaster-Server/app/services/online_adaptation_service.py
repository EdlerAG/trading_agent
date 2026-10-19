import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import numpy as np
import orjson

from app.core.config import settings
from app.domain.interfaces import IOnlineLearner


class OnlineAdaptationService(IOnlineLearner):
    """
    Дворівневий модуль безперервного самонавчання в реальному часі (Zero Memory Leak)
    із повною персистентністю останніх цін та прогнозів у storage/adaptive_weights.json.
    """

    __slots__ = ("_learning_rate_mwu", "_learning_rate_bandit", "_total_updates", "_assets", "_last_prices", "_last_preds")

    def __init__(self) -> None:
        self._learning_rate_mwu: float = 0.08
        self._learning_rate_bandit: float = 0.04
        self._total_updates: int = 0
        self._assets: Dict[str, Dict[str, Any]] = {}
        self._last_prices: Dict[str, float] = {}
        self._last_preds: Dict[str, List[float]] = {}

    @property
    def name(self) -> str:
        return "OnlineAdaptationService"

    async def init(self) -> None:
        self.load_state()

    async def shutdown(self) -> None:
        self.save_state()

    def _ensure_asset(self, symbol: str) -> Dict[str, Any]:
        sym = symbol.upper()
        if sym not in self._assets:
            self._assets[sym] = {
                "pod_eq": 1000.0,
                "pod_ema": 1000.0,
                "pod_peak": 1000.0,
                "pod_dd": 0.0,
                "online_mult": 1.05,
                "bandit_6_weights": [0.20, 0.20, 0.15, 0.25, 0.10, 0.10],
                "bandit_5_weights": [0.27, 0.10, 0.45, 0.10, 0.08],
                "cumulative_ic_ema": 0.0,
                "last_price": 0.0,
                "last_preds": [],
            }
        return self._assets[sym]

    def load_state(self) -> None:
        if not os.path.exists(settings.ONLINE_LEARNING_FILE):
            for s in settings.DEFAULT_SYMBOLS:
                self._ensure_asset(s)
            self.save_state()
            return
        try:
            with open(settings.ONLINE_LEARNING_FILE, "rb") as f:
                data = orjson.loads(f.read())
            self._learning_rate_mwu = float(data.get("learning_rate_mwu", 0.08))
            self._learning_rate_bandit = float(data.get("learning_rate_bandit", 0.04))
            self._total_updates = int(data.get("total_updates", 0))
            raw_assets = data.get("assets", {})
            for s, st in raw_assets.items():
                sym = s.upper()
                entry = self._ensure_asset(sym)
                lp = float(st.get("last_price", 0.0))
                lpreds = list(st.get("last_preds", []))
                entry.update({
                    "pod_eq": float(st.get("pod_eq", 1000.0)),
                    "pod_ema": float(st.get("pod_ema", 1000.0)),
                    "pod_peak": float(st.get("pod_peak", 1000.0)),
                    "pod_dd": float(st.get("pod_dd", 0.0)),
                    "online_mult": float(st.get("online_mult", 1.05)),
                    "bandit_6_weights": list(st.get("bandit_6_weights", entry["bandit_6_weights"])),
                    "bandit_5_weights": list(st.get("bandit_5_weights", entry["bandit_5_weights"])),
                    "cumulative_ic_ema": float(st.get("cumulative_ic_ema", 0.0)),
                    "last_price": lp,
                    "last_preds": lpreds,
                })
                if lp > 0:
                    self._last_prices[sym] = lp
                if lpreds:
                    self._last_preds[sym] = lpreds
        except Exception:
            pass

    def save_state(self) -> None:
        for sym, st in self._assets.items():
            if sym in self._last_prices:
                st["last_price"] = round(float(self._last_prices[sym]), 6)
            if sym in self._last_preds:
                st["last_preds"] = [round(float(x), 5) for x in self._last_preds[sym]]

        payload = {
            "schema_version": "23.0",
            "learning_rate_mwu": self._learning_rate_mwu,
            "learning_rate_bandit": self._learning_rate_bandit,
            "total_updates": self._total_updates,
            "assets": self._assets,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            tmp = settings.ONLINE_LEARNING_FILE + ".tmp"
            with open(tmp, "wb") as f:
                f.write(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
            os.replace(tmp, settings.ONLINE_LEARNING_FILE)
        except Exception:
            pass

    def get_asset_learning_state(self, symbol: str) -> Dict[str, Any]:
        return self._ensure_asset(symbol)

    def get_all_learning_states(self) -> Dict[str, Dict[str, Any]]:
        return self._assets

    def record_step_and_adapt(
        self,
        symbol: str,
        prev_price: float,
        curr_price: float,
        prev_model_pos: float,
        tier_role: int,
        new_submodel_preds: Optional[list] = None,
    ) -> float:
        sym = symbol.upper()
        st = self._ensure_asset(sym)
        if not settings.ENABLE_ONLINE_LEARNING:
            return float(st["online_mult"])

        ref_prev_p = prev_price if prev_price > 0 else self._last_prices.get(sym, float(st.get("last_price", 0.0)))
        if ref_prev_p > 0 and curr_price > 0:
            bar_ret = (curr_price - ref_prev_p) / ref_prev_p
            bar_ret = max(-0.15, min(0.15, bar_ret))

            pod_eq = float(st["pod_eq"]) * (1.0 + float(prev_model_pos) * 0.50 * bar_ret)
            pod_ema = 0.996 * float(st["pod_ema"]) + 0.004 * pod_eq
            pod_peak = max(float(st["pod_peak"]), pod_eq)
            p_dd = (pod_peak - pod_eq) / max(1.0, pod_peak)
            above_ema = pod_eq >= (pod_ema * 0.995)

            if tier_role == 1:
                mult = 1.25 if (p_dd < 0.06 and above_ema) else (0.75 if p_dd > 0.14 else 1.05)
            elif tier_role == 2:
                mult = 1.15 if (p_dd < 0.07 and above_ema) else (0.50 if p_dd > 0.12 else 0.90)
            else:
                mult = 0.85 if (pod_eq > 1020.0 and p_dd < 0.06 and above_ema) else 0.10

            st["pod_eq"] = round(pod_eq, 3)
            st["pod_ema"] = round(pod_ema, 3)
            st["pod_peak"] = round(pod_peak, 3)
            st["pod_dd"] = round(p_dd * 100.0, 2)
            st["online_mult"] = round(mult, 3)

            prev_preds = self._last_preds.get(sym) or st.get("last_preds")
            if prev_preds and abs(bar_ret) > 1e-5:
                realized_dir = np.sign(bar_ret)
                n_m = len(prev_preds)
                w_key = "bandit_6_weights" if n_m == 6 else "bandit_5_weights"
                cur_w = np.asarray(st.get(w_key, [1.0 / n_m] * n_m), dtype=np.float64)
                if len(cur_w) == n_m:
                    rewards = np.clip(np.tanh(np.asarray(prev_preds, dtype=np.float64)) * realized_dir, -1.0, 1.0)
                    updated_w = cur_w * np.exp(self._learning_rate_bandit * rewards)
                    updated_w = np.maximum(0.03, updated_w)
                    updated_w /= np.sum(updated_w)
                    st[w_key] = [round(float(x), 4) for x in updated_w]

                mean_align = float(np.mean(np.sign(prev_preds) * realized_dir))
                st["cumulative_ic_ema"] = round(0.98 * float(st.get("cumulative_ic_ema", 0.0)) + 0.02 * mean_align, 4)

            self._total_updates += 1

        if curr_price > 0:
            self._last_prices[sym] = curr_price
            st["last_price"] = round(curr_price, 6)
        if new_submodel_preds:
            self._last_preds[sym] = list(new_submodel_preds)
            st["last_preds"] = [round(float(x), 5) for x in new_submodel_preds]

        return float(st["online_mult"])

    def get_summary_dict(self) -> Dict[str, Any]:
        return {
            "enabled": settings.ENABLE_ONLINE_LEARNING,
            "total_updates": self._total_updates,
            "assets": {
                sym: {
                    "pod_eq": st["pod_eq"],
                    "pod_dd_pct": st["pod_dd"],
                    "online_mult": st["online_mult"],
                    "ic_ema": st.get("cumulative_ic_ema", 0.0),
                    "bandit_6_weights": st.get("bandit_6_weights", []),
                }
                for sym, st in self._assets.items()
            },
        }