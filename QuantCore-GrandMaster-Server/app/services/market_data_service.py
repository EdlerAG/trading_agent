import asyncio
import inspect
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.http_client import http_pool
from app.domain.interfaces import IService, IExchangeGateway


class MarketDataService(IService):
    """
    Високошвидкісний сервіс ринкових даних V2/V3 (QuantCore Data Coordinator):
    - Конкурентно (asyncio.gather + Semaphore) оновлює свічки по всіх 32/58 активних валютах.
    - Для CARTRIDGE_ENGINE='v3' додатково підтягує 1h дельти PremiumIndex, Spot Volume, OI та L/S
      із локальним кільцевим кешем у пам'яті (< 4 MB RAM на всі 58 монет).
    """

    __slots__ = ("_logger", "_exchange", "_last_synced_ts", "_v3_aux_cache")

    def __init__(self, logger: logging.Logger, exchange_service: IExchangeGateway) -> None:
        self._logger = logger
        self._exchange = exchange_service
        self._last_synced_ts: str = ""
        self._v3_aux_cache: Dict[str, Tuple[float, Dict[int, Tuple[float, float, float, float, float, float]]]] = {}

    @property
    def name(self) -> str:
        return "MarketDataService"

    @property
    def last_synced_timestamp(self) -> str:
        return self._last_synced_ts

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    @staticmethod
    def _bar_ts_ms(df: pd.DataFrame) -> np.ndarray:
        if "open_ms" in df.columns:
            return pd.to_numeric(df["open_ms"], errors="coerce").to_numpy(np.int64)
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            return (ts.astype("int64") // 10 ** 6).to_numpy(np.int64)
        return np.arange(len(df), dtype=np.int64) * 3_600_000

    def _apply_funding_series(
        self,
        df: pd.DataFrame,
        live_rate: float,
        history: Optional[pd.DataFrame],
    ) -> None:
        """Кожному бару — остання ставка фандінгу, відома НА ЦЕЙ бар.

        Раніше сервер писав одну й ту саму ставку в усі 1950 барів, через що
        funding_z_168 був тотожно 0, а фільтр перегріву не працював.
        Поточна ставка з fetch_funding_rates ставиться лише на останній бар.
        """
        ts = self._bar_ts_ms(df)
        if history is None or len(history) == 0 or "timestamp" not in history.columns:
            df["funding_rate"] = float(live_rate)
            df["funding_interval"] = 8.0
            return
        ev = history.dropna(subset=["timestamp", "funding_rate"])
        if len(ev) == 0:
            df["funding_rate"] = float(live_rate)
            df["funding_interval"] = 8.0
            return
        ev_ts = pd.to_numeric(ev["timestamp"], errors="coerce").to_numpy(np.int64)
        ev_rate = pd.to_numeric(ev["funding_rate"], errors="coerce").to_numpy(np.float64)
        order = np.argsort(ev_ts)
        ev_ts, ev_rate = ev_ts[order], ev_rate[order]
        # +60_000 мс захищає від ±мс джитера Binance calc_time (08:00:00.005 -> бар 08:00:00)
        pos = np.searchsorted(ev_ts, ts + 60_000, side="right") - 1
        rates = np.where(
            pos >= 0,
            ev_rate[np.clip(pos, 0, len(ev_rate) - 1)],
            0.0,
        )
        if len(rates) and np.isfinite(live_rate):
            rates[-1] = float(live_rate)
        df["funding_rate"] = rates

        # Каузальна оцінка інтервалу виплати фандінгу (4h vs 8h) з попередніх подій
        if len(ev_ts) >= 2:
            ev_dt_h = np.diff(ev_ts, prepend=ev_ts[0] - 8 * 3_600_000) / 3_600_000.0
            ev_int = np.where(ev_dt_h <= 5.0, 4.0, 8.0)
            df["funding_interval"] = np.where(
                pos >= 0,
                ev_int[np.clip(pos, 0, len(ev_int) - 1)],
                8.0,
            )
        else:
            df["funding_interval"] = 8.0

    async def _fetch_v3_aux_for_symbol(self, sym: str, target_bars: int = 240) -> Dict[int, Tuple[float, float, float, float, float, float]]:
        """Надлегке асинхронне отримання V3 каналів (premium, spot_qv, spot_tq, oi_usd, top_ls, glob_ls) із дельта-кешем."""
        import time
        now_s = time.time()
        sym_u = sym.upper()
        cached = self._v3_aux_cache.get(sym_u)
        is_warm = cached is not None and len(cached[1]) >= 180
        # Якщо вже оновлювали < 50 хв тому — повертаємо з пам'яті за 0 мс!
        if is_warm and (now_s - cached[0]) < 3000.0:
            return cached[1]

        lim_k = 8 if is_warm else min(500, max(210, target_bars))
        lim_m = 8 if is_warm else min(500, max(210, target_bars))
        spot_sym = sym_u[4:] if sym_u.startswith("1000") else sym_u
        client = http_pool.get()
        now_ms = int(now_s * 1000)

        async def _safe_json(url: str, params: Dict[str, object]) -> list:
            try:
                r = await client.get(url, params=params, timeout=7.5)
                if r.status_code == 200:
                    d = r.json()
                    return d if isinstance(d, list) else []
            except Exception:
                pass
            return []

        prem_r, spot_r, oi_r, tls_r, gls_r = await asyncio.gather(
            _safe_json("https://fapi.binance.com/fapi/v1/premiumIndexKlines", {"symbol": sym_u, "interval": "1h", "limit": lim_k}),
            _safe_json("https://api.binance.com/api/v3/klines", {"symbol": spot_sym, "interval": "1h", "limit": lim_k}),
            _safe_json("https://fapi.binance.com/futures/data/openInterestHist", {"symbol": sym_u, "period": "1h", "limit": lim_m}),
            _safe_json("https://fapi.binance.com/futures/data/topLongShortPositionRatio", {"symbol": sym_u, "period": "1h", "limit": lim_m}),
            _safe_json("https://fapi.binance.com/futures/data/globalLongShortAccountRatio", {"symbol": sym_u, "period": "1h", "limit": lim_m}),
        )

        merged: Dict[int, List[float]] = {
            k: list(v) for k, v in (cached[1].items() if cached else {})
        }

        def _row(ts_open: int) -> List[float]:
            cur = merged.get(ts_open)
            if cur is None:
                cur = [np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
                merged[ts_open] = cur
            return cur

        for k in prem_r:
            if len(k) >= 7 and int(k[6]) < now_ms:
                _row(int(k[0]))[0] = float(k[4])
        for k in spot_r:
            if len(k) >= 11 and int(k[6]) < now_ms:
                r_l = _row(int(k[0]))
                r_l[1] = float(k[7])
                r_l[2] = float(k[10])
        for item in oi_r:
            ts_m = int(item.get("timestamp") or 0)
            if ts_m > 0 and item.get("sumOpenInterestValue") is not None:
                _row(((ts_m - 1) // 3_600_000) * 3_600_000)[3] = float(item["sumOpenInterestValue"])
        for item in tls_r:
            ts_m = int(item.get("timestamp") or 0)
            if ts_m > 0 and item.get("longShortRatio") is not None:
                _row(((ts_m - 1) // 3_600_000) * 3_600_000)[4] = float(item["longShortRatio"])
        for item in gls_r:
            ts_m = int(item.get("timestamp") or 0)
            if ts_m > 0 and item.get("longShortRatio") is not None:
                _row(((ts_m - 1) // 3_600_000) * 3_600_000)[5] = float(item["longShortRatio"])

        # Обмежуємо кільцевий буфер до останніх 540 годин (~25 КБ на монету!)
        sorted_keys = sorted(merged)[-540:]
        compact = {k: (merged[k][0], merged[k][1], merged[k][2], merged[k][3], merged[k][4], merged[k][5]) for k in sorted_keys}
        self._v3_aux_cache[sym_u] = (now_s, compact)
        return compact

    @classmethod
    def _inject_v3_aux_series(cls, df: pd.DataFrame, aux_map: Dict[int, Tuple[float, float, float, float, float, float]]) -> None:
        if not aux_map:
            return
        ts = cls._bar_ts_ms(df)
        n = len(ts)
        prm = np.full(n, np.nan, dtype=np.float32)
        sqv = np.full(n, np.nan, dtype=np.float32)
        stq = np.full(n, np.nan, dtype=np.float32)
        oi = np.full(n, np.nan, dtype=np.float32)
        tls = np.full(n, np.nan, dtype=np.float32)
        gls = np.full(n, np.nan, dtype=np.float32)
        last_oi = last_tl = last_gl = np.nan
        gap = 0
        for i, t_ms in enumerate(ts):
            rec = aux_map.get(int(t_ms))
            if rec is not None:
                prm[i] = rec[0]
                sqv[i] = rec[1]
                stq[i] = rec[2]
                if np.isfinite(rec[3]):
                    last_oi, gap = rec[3], 0
                else:
                    gap += 1
                if np.isfinite(rec[4]):
                    last_tl = rec[4]
                if np.isfinite(rec[5]):
                    last_gl = rec[5]
            else:
                gap += 1
            if gap <= 6:
                oi[i] = last_oi
                tls[i] = last_tl
                gls[i] = last_gl
        df["premium_close"] = prm
        df["spot_quote_volume"] = sqv
        df["spot_taker_quote"] = stq
        df["oi_usd"] = oi
        df["top_ls_ratio"] = tls
        df["global_ls_ratio"] = gls

    async def fetch_synchronized_candles(
        self,
        symbols: Tuple[str, ...],
        min_bars: int = 200,
    ) -> Dict[str, pd.DataFrame]:
        """
        Конкурентно завантажує свічки та ставки фінансування (funding rates) для всіх монет кошика.
        Записує отримане значення ставки у колонку df["funding_rate"] кожної монети, щоб ознака funding_rate_z
        у feature_pipe_v58.py працювала на реальних даних біржі.
        """
        candles_map: Dict[str, pd.DataFrame] = {}
        sem = asyncio.Semaphore(8)

        async def _fetch_single_symbol(sym: str) -> Tuple[str, Optional[pd.DataFrame]]:
            async with sem:
                try:
                    df = await asyncio.wait_for(
                        self._exchange.fetch_delta_candles(sym, limit=settings.effective_candles_limit),
                        timeout=15.0,
                    )
                    return sym.upper(), df
                except Exception as e:
                    self._logger.warning(f"⚠️ [{sym}] Помилка завантаження свічок: {e}")
                    return sym.upper(), None

        async def _fetch_funding() -> Dict[str, float]:
            try:
                if hasattr(self._exchange, "fetch_funding_rates"):
                    return await asyncio.wait_for(
                        self._exchange.fetch_funding_rates(symbols),
                        timeout=10.0,
                    )
                return {}
            except Exception as e:
                self._logger.warning(f"⚠️ Помилка завантаження funding rates: {e}")
                return {}

        async def _fetch_funding_history() -> Dict[str, pd.DataFrame]:
            fn = getattr(self._exchange, "fetch_funding_history", None)
            # MagicMock-заглушки в тестах не є корутинами -> тихий fallback.
            if not callable(fn) or not inspect.iscoroutinefunction(fn):
                return {}
            try:
                hist = await asyncio.wait_for(
                    fn(symbols, hours=settings.FUNDING_HISTORY_HOURS),
                    timeout=20.0,
                )
                return hist if isinstance(hist, dict) else {}
            except Exception as e:
                self._logger.warning(f"⚠️ Помилка завантаження funding history: {e}")
                return {}

        # Паралельне асинхронне виконання запитів до біржі: свічки + фандінг
        candles_task = asyncio.gather(*[_fetch_single_symbol(sym) for sym in symbols])
        funding_task = _fetch_funding()
        history_task = _fetch_funding_history()

        candles_results, funding_map, funding_history = await asyncio.gather(
            candles_task, funding_task, history_task
        )

        # Підвантаження V3 допоміжних каналів тільки коли активне ядро V3 та реальний біржовий шлюз
        v3_aux_by_sym: Dict[str, Dict[int, Tuple[float, float, float, float, float, float]]] = {}
        is_real_gateway = getattr(self._exchange, "_exchange", None) is not None
        if settings.CARTRIDGE_ENGINE in ("v3", "v4", "v5") and settings.ENABLE_V3_AUX_CHANNELS and is_real_gateway:
            aux_sem = asyncio.Semaphore(8)

            async def _pull_aux(s: str):
                async with aux_sem:
                    return s.upper(), await self._fetch_v3_aux_for_symbol(s, target_bars=settings.effective_candles_limit)

            for s_k, aux_d in await asyncio.gather(*[_pull_aux(sym) for sym in symbols]):
                v3_aux_by_sym[s_k] = aux_d

        for sym_u, df in candles_results:
            if df is not None and len(df) >= min_bars:
                fr_rate = float(funding_map.get(sym_u, 0.0))
                self._apply_funding_series(df, fr_rate, funding_history.get(sym_u))
                if sym_u in v3_aux_by_sym:
                    self._inject_v3_aux_series(df, v3_aux_by_sym[sym_u])
                candles_map[sym_u] = df
            else:
                self._logger.warning(
                    f"⚠️ [{sym_u}] Отримано недостатньо свічок ({0 if df is None else len(df)} < {min_bars})."
                )

        if "BTCUSDT" in candles_map and "timestamp" in candles_map["BTCUSDT"].columns:
            self._last_synced_ts = str(candles_map["BTCUSDT"]["timestamp"].iloc[-1])

        return candles_map
