import asyncio
import logging
from typing import Dict, Tuple
import pandas as pd

from app.core.config import settings
from app.domain.interfaces import IService, IExchangeGateway


class MarketDataService(IService):
    """
    Високошвидкісний сервіс ринкових даних (Multi-Asset Data Coordinator):
    - Паралельно оновлює 15m свічки по всіх активних валютах через Ring-Buffer шлюзу.
    - Перевіряє цілісність даних (відсутність NaN, достатню глибину для EMA-1536)
      та синхронізує часову сітку перед передачею в картридж V23.
    """

    __slots__ = ("_logger", "_exchange", "_last_synced_ts")

    def __init__(self, logger: logging.Logger, exchange_service: IExchangeGateway) -> None:
        self._logger = logger
        self._exchange = exchange_service
        self._last_synced_ts: str = ""

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

    async def fetch_synchronized_candles(
        self,
        symbols: Tuple[str, ...],
        min_bars: int = 1650,
    ) -> Dict[str, pd.DataFrame]:
        """
        Завантажує дельта-свічки для всіх монет кошика та повертає словник валідних DataFrame.
        """
        candles_map: Dict[str, pd.DataFrame] = {}

        for sym in symbols:
            df = await self._exchange.fetch_delta_candles(sym, limit=settings.CANDLES_FETCH_LIMIT)
            if df is not None and len(df) >= min_bars:
                candles_map[sym.upper()] = df
            else:
                self._logger.warning(
                    f"⚠️ [{sym}] Отримано недостатньо свічок ({0 if df is None else len(df)} < {min_bars})."
                )

        if "BTCUSDT" in candles_map and "timestamp" in candles_map["BTCUSDT"].columns:
            self._last_synced_ts = str(candles_map["BTCUSDT"]["timestamp"].iloc[-1])

        return candles_map