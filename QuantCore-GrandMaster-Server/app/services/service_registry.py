import asyncio
import logging
from typing import Any, Optional

from app.core.config import settings
from app.core.http_client import http_pool
from app.core.events import event_bus
from app.core.memory_guard import memory_guard
from app.services.state_service import StateService
from app.services.database_service import DatabaseService
from app.services.exchange_ccxt_service import ExchangeCcxtService
from app.services.market_data_service import MarketDataService
from app.services.risk_guard_service import RiskGuardService
from app.services.execution_service import MultiAssetExecutionOrchestrator
from app.services.telegram_bot_service import TelegramBotService
from app.cartridges.cartridge_loader import CartridgeLoaderService


class _NoOpOnlineLearner:
    """Нульовий за пам'яттю адаптер при вимкненому ENABLE_ONLINE_LEARNING (0 байтів V58 ваг у RAM)."""

    name = "NoOpOnlineLearner"

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_all_learning_states(self) -> dict:
        return {}

    def get_summary_dict(self) -> dict:
        return {"enabled": False}

    def save_state(self) -> None:
        pass


class _NoOpNewsService:
    """Нульовий за пам'яттю адаптер при вимкненому ENABLE_NEWS_SENTIMENT (без RSS/Gemini у RAM)."""

    name = "NoOpNewsService"
    geo_shock_prob: float = 0.0

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def fetch_market_intelligence(self, force_refresh: bool = False) -> dict:
        _ = force_refresh
        return {"macro_sentiment": 0.0, "is_geo_shock": False, "geo_shock_prob": 0.0, "headlines": [], "coin_bias": {}}

    def get_cached_info(self) -> dict:
        return {"enabled": False, "macro_sentiment": 0.0, "is_geo_shock": False, "geo_shock_prob": 0.0, "headlines": []}


class ApplicationContainer:
    """DI-Контейнер мікросервісів із лінивим завантаженням (0 зайвих модулів у RAM та 0% Idle CPU)."""

    __slots__ = (
        "logger",
        "state_service",
        "online_learner",
        "db_service",
        "cartridge_service",
        "exchange_service",
        "market_data_service",
        "currency_governor",
        "risk_guard",
        "news_service",
        "shadow_arena",
        "orchestrator",
        "telegram_bot",
        "ws_sentinel",
        "watchdog",
    )

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        is_v2_family = settings.CARTRIDGE_ENGINE in ("v2", "v3", "v4", "v5", "v6", "qv3", "qv3_convex")

        self.state_service = StateService()
        if settings.ENABLE_ONLINE_LEARNING and not is_v2_family:
            from app.services.online_adaptation_service import OnlineAdaptationService
            self.online_learner: Any = OnlineAdaptationService()
        else:
            self.online_learner = _NoOpOnlineLearner()

        self.db_service = DatabaseService()
        self.cartridge_service = CartridgeLoaderService(logger=logger)
        self.exchange_service = ExchangeCcxtService(logger=logger, db_service=self.db_service)
        self.market_data_service = MarketDataService(logger=logger, exchange_service=self.exchange_service)

        if not is_v2_family:
            from app.services.currency_governor_service import CurrencyGovernorService
            self.currency_governor: Optional[Any] = CurrencyGovernorService(logger=logger, state_service=self.state_service)
        else:
            self.currency_governor = None

        self.risk_guard = RiskGuardService(
            logger=logger,
            state_service=self.state_service,
            db_service=self.db_service,
            exchange_service=self.exchange_service,
        )

        if settings.ENABLE_NEWS_SENTIMENT and not is_v2_family:
            from app.services.news_ai_service import NewsAiService
            self.news_service: Any = NewsAiService()
        else:
            self.news_service = _NoOpNewsService()

        if settings.ENABLE_SHADOW_ARENA:
            from app.services.shadow_arena_service import ShadowArenaService
            self.shadow_arena: Optional[Any] = ShadowArenaService(logger=logger, db_service=self.db_service)
        else:
            self.shadow_arena = None

        self.orchestrator = MultiAssetExecutionOrchestrator(
            logger=logger,
            state_service=self.state_service,
            db_service=self.db_service,
            exchange_service=self.exchange_service,
            cartridge_service=self.cartridge_service,
            online_learner=self.online_learner,
            news_service=self.news_service,
            market_data_service=self.market_data_service,
            currency_governor=self.currency_governor,
        )
        self.orchestrator.bind_shadow_arena(self.shadow_arena)
        self.orchestrator.bind_risk_guard(self.risk_guard)
        self.risk_guard.bind_orchestrator(self.orchestrator)

        self.telegram_bot = TelegramBotService(
            logger=logger,
            state_service=self.state_service,
            db_service=self.db_service,
            cartridge_service=self.cartridge_service,
            news_service=self.news_service,
            orchestrator=self.orchestrator,
        )
        self.telegram_bot.bind_extra_services(exchange_service=self.exchange_service, shadow_arena=self.shadow_arena)
        self.orchestrator.bind_telegram_sender(self.telegram_bot)

        if settings.ENABLE_WS_SENTINEL:
            from app.services.ws_sentinel_service import WebSocketSentinelService
            self.ws_sentinel: Optional[Any] = WebSocketSentinelService(
                logger=logger,
                state_service=self.state_service,
                exchange_service=self.exchange_service,
                event_bus_instance=event_bus,
                orchestrator=self.orchestrator,
            )
            self.ws_sentinel.bind_telegram_sender(self.telegram_bot)
            self.orchestrator.bind_ws_sentinel(self.ws_sentinel)
        else:
            self.ws_sentinel = None

        self.watchdog = self.risk_guard

    async def init_all(self) -> None:
        for srv in (
            self.db_service,
            self.state_service,
            self.online_learner,
            self.cartridge_service,
            self.exchange_service,
            self.market_data_service,
            self.currency_governor,
            self.risk_guard,
            self.news_service,
            self.shadow_arena,
            self.orchestrator,
            self.telegram_bot,
            self.ws_sentinel,
        ):
            if srv is not None:
                await srv.init()
        memory_guard.trim_ram()

    async def shutdown(self) -> None:
        for srv in (
            self.ws_sentinel,
            self.telegram_bot,
            self.orchestrator,
            self.shadow_arena,
            self.news_service,
            self.risk_guard,
            self.currency_governor,
            self.market_data_service,
            self.exchange_service,
            self.cartridge_service,
            self.online_learner,
            self.state_service,
            self.db_service,
        ):
            if srv is None:
                continue
            try:
                await srv.shutdown()
            except Exception:
                pass
        await http_pool.close()
        memory_guard.trim_ram()


async def build_application_container(
    base_dir: str,
    storage_dir: str,
    wakeup_event: asyncio.Event,
    logger: logging.Logger,
) -> ApplicationContainer:
    event_bus.bind_wakeup_event(wakeup_event)
    container = ApplicationContainer(logger=logger)
    await container.init_all()
    return container
