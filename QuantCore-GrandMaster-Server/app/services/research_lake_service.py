# -*- coding: utf-8 -*-
"""Research Data Lake для майбутньої розробки V3 (`data/v3_research_lake/`).

Зберігає стиснені append-only `.jsonl.gz` потоки поза папкою `storage/` (щоб LRU-квота `storage/`
не видаляла дослідницькі дані), із власною захисною ротацією `<= MAX_RESEARCH_LAKE_MB` (дефолт 1024 МБ):
  1. `bar_features_YYYY-MM-DD.jsonl.gz`
  2. `order_lifecycle_YYYY-MM-DD.jsonl.gz`
  3. `sentinel_events_YYYY-MM-DD.jsonl.gz`
  4. `stop_tp_events_YYYY-MM-DD.jsonl.gz`
"""
from __future__ import annotations

import gzip
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.config import settings


class ResearchLakeService:
    """Потокобезпечний append-only записувач стиснених `.jsonl.gz` таблиць для V3 Research."""

    __slots__ = ("_root_dir", "_max_bytes", "_lock", "_enabled")

    TABLES = ("bar_features", "order_lifecycle", "sentinel_events", "stop_tp_events")

    def __init__(
        self,
        root_dir: Optional[str] = None,
        max_mb: Optional[int] = None,
        enabled: Optional[bool] = None,
        lake_dir: Optional[str] = None,
    ) -> None:
        eff_dir = root_dir or lake_dir or getattr(settings, "V3_RESEARCH_LAKE_DIR", os.path.join(settings.BASE_DIR, "data", "v3_research_lake"))
        self._root_dir = Path(eff_dir)
        eff_mb = int(max_mb if max_mb is not None else getattr(settings, "MAX_RESEARCH_LAKE_MB", 1024))
        self._max_bytes = max(1, eff_mb) * 1024 * 1024
        self._lock = threading.Lock()
        self._enabled = bool(getattr(settings, "ENABLE_V3_RESEARCH_LAKE", True) if enabled is None else enabled)
        if self._enabled:
            self._root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def _append_rows(self, table_name: str, rows: List[Dict[str, Any]]) -> None:
        if not self._enabled or not rows or table_name not in self.TABLES:
            return
        day_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_p = self._root_dir / f"{table_name}_{day_str}.jsonl.gz"
        try:
            self._root_dir.mkdir(parents=True, exist_ok=True)
            payload = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")
            with self._lock:
                with gzip.open(out_p, "ab", compresslevel=6) as gz:
                    gz.write(payload)
            self.enforce_quota()
        except Exception:
            pass

    def record_bar_features(
        self,
        candle_ts: str,
        prices: Mapping[str, float],
        factors: Mapping[str, Mapping[str, float]],
        funding_rates: Optional[Mapping[str, float]] = None,
        regime: str = "T1",
        breadth: float = 0.0,
        dispersion: float = 0.0,
        btc_trend: float = 0.0,
        weights_net: Optional[Mapping[str, float]] = None,
    ) -> None:
        if not self._enabled:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        w_map = weights_net or {}
        f_rates = funding_rates or {}
        rows: List[Dict[str, Any]] = []
        for sym in sorted(set(prices.keys()) | set(factors.keys())):
            px = float(prices.get(sym, 0.0) or 0.0)
            if px <= 0.0:
                continue
            f = factors.get(sym) or {}
            rows.append({
                "stream": "bar_features",
                "recorded_at": now_iso,
                "timestamp": str(candle_ts),
                "symbol": str(sym).upper(),
                "mark_price": round(px, 6),
                "funding_rate": float(f_rates.get(sym, 0.0) or 0.0),
                "alpha_score": round(float(f.get("score", 0.0) or 0.0), 5),
                "desired_weight": round(float(w_map.get(sym, 0.0) or 0.0), 5),
                "beta": round(float(f.get("beta_btc", 1.0) or 1.0), 4),
                "z_mom": round(float(f.get("z_mom", 0.0) or 0.0), 4),
                "z_carry": round(float(f.get("z_carry", 0.0) or 0.0), 4),
                "z_bab": round(float(f.get("z_bab", 0.0) or 0.0), 4),
                "z_flow": round(float(f.get("z_flow", 0.0) or 0.0), 4),
                "z_spot": round(float(f.get("z_spot", 0.0) or 0.0), 4),
                "z_smart_oi": round(float(f.get("z_smart_oi", 0.0) or 0.0), 4),
                "regime": str(regime),
                "regime_btc_trend": round(float(btc_trend), 5),
                "breadth": round(float(breadth), 4),
                "cs_dispersion": round(float(dispersion), 5),
            })
        self._append_rows("bar_features", rows)

    def record_bar_features_snapshot(
        self,
        candle_ts: str,
        factors_map: Mapping[str, Mapping[str, float]],
        targets_map: Mapping[str, Any],
        btc_trend: float,
        market_breadth: float,
        cs_dispersion: float,
        bbo_map: Optional[Mapping[str, Mapping[str, float]]] = None,
        funding_map: Optional[Mapping[str, float]] = None,
    ) -> None:
        if not self._enabled:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        rows: List[Dict[str, Any]] = []
        all_syms = sorted(set(factors_map.keys()) | set(targets_map.keys()))
        for sym in all_syms:
            f = factors_map.get(sym) or {}
            t_dto = targets_map.get(sym)
            bbo = (bbo_map or {}).get(sym) or {}
            px = float(getattr(t_dto, "current_price", 0.0) or bbo.get("mark_price", 0.0) or 0.0)
            if px <= 0.0:
                continue
            rows.append({
                "recorded_at": now_iso,
                "timestamp": str(candle_ts),
                "symbol": sym,
                "mark_price": round(px, 6),
                "funding_rate": float((funding_map or {}).get(sym, bbo.get("funding_rate", 0.0)) or 0.0),
                "bbo_spread_bps": round(float(bbo.get("spread_bps", 0.0) or 0.0), 3),
                "alpha_score": round(float(f.get("score", getattr(t_dto, "alpha_score", 0.0)) or 0.0), 5),
                "desired_weight": round(float(getattr(t_dto, "desired_weight", 0.0) or 0.0), 5),
                "beta": round(float(f.get("beta_btc", 1.0) or 1.0), 4),
                "z_mom": round(float(f.get("z_mom", 0.0) or 0.0), 4),
                "z_carry": round(float(f.get("z_carry", 0.0) or 0.0), 4),
                "z_bab": round(float(f.get("z_bab", 0.0) or 0.0), 4),
                "z_flow": round(float(f.get("z_flow", 0.0) or 0.0), 4),
                "z_spot": round(float(f.get("z_spot", 0.0) or 0.0), 4),
                "z_smart_oi": round(float(f.get("z_smart_oi", 0.0) or 0.0), 4),
                "regime_btc_trend": round(float(btc_trend), 5),
                "breadth": round(float(market_breadth), 4),
                "cs_dispersion": round(float(cs_dispersion), 5),
            })
        self._append_rows("bar_features", rows)

    def record_order_lifecycle(self, event: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
        if not self._enabled:
            return
        merged = dict(event or {})
        merged.update(kwargs)
        row = {"stream": "order_lifecycle", "recorded_at": datetime.now(timezone.utc).isoformat(), **merged}
        self._append_rows("order_lifecycle", [row])

    def record_sentinel_event(
        self,
        symbol: str,
        atr_move: float,
        direction: str,
        price_at_trigger: float,
        open_price: float = 0.0,
    ) -> None:
        if not self._enabled:
            return
        self._append_rows("sentinel_events", [{
            "stream": "sentinel_events",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": str(symbol).upper(),
            "atr_move": round(float(atr_move), 3),
            "direction": str(direction),
            "price_at_trigger": float(price_at_trigger),
            "candle_open_price": float(open_price),
        }])

    def record_stop_tp_event(
        self,
        symbol: str,
        event_kind: str = "",
        close_side: str = "",
        closed_qty: float = 0.0,
        fill_price: float = 0.0,
        realized_pnl_usd: float = 0.0,
        fee_usd: float = 0.0,
        net_exposure_before: float = 0.0,
        net_exposure_after: float = 0.0,
        **kwargs: Any,
    ) -> None:
        if not self._enabled:
            return
        row = {
            "stream": "stop_tp_events",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": str(symbol).upper(),
            "event_kind": str(event_kind or kwargs.get("event_type", "STOP_HIT")),
            "close_side": str(close_side or kwargs.get("side", "")),
            "closed_qty": round(float(closed_qty or kwargs.get("qty", 0.0)), 6),
            "fill_price": float(fill_price),
            "realized_pnl_usd": round(float(realized_pnl_usd or kwargs.get("realized_pnl", 0.0)), 5),
            "fee_usd": round(float(fee_usd), 5),
            "net_exposure_before": round(float(net_exposure_before), 5),
            "net_exposure_after": round(float(net_exposure_after), 5),
            **{k: v for k, v in kwargs.items() if k not in ("event_type", "side", "qty", "realized_pnl")},
        }
        self._append_rows("stop_tp_events", [row])

    def get_lake_stats(self) -> Dict[str, Any]:
        files = sorted(self._root_dir.glob("*.jsonl.gz")) if self._root_dir.exists() else []
        total_b = sum(p.stat().st_size for p in files if p.exists())
        by_table: Dict[str, int] = {t: 0 for t in self.TABLES}
        for p in files:
            for t in self.TABLES:
                if p.name.startswith(t + "_"):
                    by_table[t] += p.stat().st_size
        return {
            "enabled": self._enabled,
            "lake_dir": str(self._root_dir),
            "files_count": len(files),
            "files": [p.name for p in files[-16:]],
            "total_mb": round(total_b / (1024.0 * 1024.0), 4),
            "max_mb": round(self._max_bytes / (1024.0 * 1024.0), 1),
            "streams_bytes": by_table,
        }

    def enforce_quota(self) -> int:
        if not self._root_dir.exists():
            return 0
        files: List[Tuple[float, int, Path]] = []
        total_b = 0
        for p in self._root_dir.glob("*.jsonl.gz"):
            try:
                st = p.stat()
                total_b += st.st_size
                files.append((st.st_mtime, st.st_size, p))
            except OSError:
                continue
        if total_b <= self._max_bytes:
            return 0
        files.sort(key=lambda x: x[0])
        target_b = int(self._max_bytes * 0.85)
        freed = 0
        for _mt, sz, p in files:
            try:
                p.unlink()
                total_b -= sz
                freed += sz
                if total_b <= target_b:
                    break
            except OSError:
                continue
        return freed


research_lake = ResearchLakeService()
