import os
import signal
import asyncio
import logging
from fastapi import Depends, Request
from app.core.http_client import http_pool
from app.core.events import event_bus
from app.core.security import verify_api_access
from app.core.memory_guard import memory_guard
from app.services.state_service import StateService
from app.services.online_adaptation_service import OnlineAdaptationService
from app.services.database_service import DatabaseService
from app.services.exchange_ccxt_service import ExchangeCcxtService
from app.services.news_ai_service import NewsAiService
from app.services.execution_service import MultiAssetExecutionOrchestrator
from app.services.telegram_bot_service import TelegramBotService
from app.cartridges.cartridge_loader import CartridgeLoaderService


class ApplicationContainer:
    """DI-Контейнер усіх мікросервісів системи з єдиним життєвим циклом."""

    __slots__ = (
        "logger",
        "state_service",
        "online_learner",
        "db_service",
        "cartridge_service",
        "cartridge_Service",  # Аліас для повної сумісності з main.py
        "exchange_service",
        "news_service",
        "orchestrator",
        "telegram_bot",
        "watchdog",
    )

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.state_service = StateService()
        self.online_learner = OnlineAdaptationService()
        self.db_service = DatabaseService()
        self.cartridge_service = CartridgeLoaderService(logger=logger)
        self.cartridge_Service = self.cartridge_service
        self.exchange_service = ExchangeCcxtService(logger=logger, db_service=self.db_service)
        self.news_service = NewsAiService()

        self.orchestrator = MultiAssetExecutionOrchestrator(
            logger=logger,
            state_service=self.state_service,
            db_service=self.db_service,
            exchange_service=self.exchange_service,
            cartridge_service=self.cartridge_service,
            online_learner=self.online_learner,
            news_service=self.news_service,
        )

        self.telegram_bot = TelegramBotService(
            logger=logger,
            state_service=self.state_service,
            db_service=self.db_service,
            cartridge_service=self.cartridge_service,
            news_service=self.news_service,
            orchestrator=self.orchestrator,
        )
        self.orchestrator.bind_telegram_sender(self.telegram_bot)
        self.watchdog = None

    async def init_all(self) -> None:
        for srv in (
            self.db_service,
            self.state_service,
            self.online_learner,
            self.cartridge_service,
            self.exchange_service,
            self.news_service,
            self.orchestrator,
            self.telegram_bot,
        ):
            await srv.init()
        memory_guard.trim_ram()

    async def shutdown(self) -> None:
        for srv in (
            self.telegram_bot,
            self.orchestrator,
            self.news_service,
            self.exchange_service,
            self.cartridge_service,
            self.online_learner,
            self.state_service,
            self.db_service,
        ):
            try:
                await srv.shutdown()
            except Exception:
                pass
        await http_pool.close()
        memory_guard.trim_ram()


def _register_restart_endpoint() -> None:
    """Додає ендпоінт /api/v1/control/restart для 1-клік перезавантаження сервера з Веб-термінала."""
    try:
        from app.api.endpoints_control import router as ctrl_router
        paths = [getattr(r, "path", "") for r in ctrl_router.routes]
        if "/api/v1/control/restart" not in paths:
            @ctrl_router.post("/restart")
            async def restart_server_from_web(request: Request, _: str = Depends(verify_api_access)):
                container = getattr(request.app.state, "container", None)
                if container is not None and container.telegram_bot is not None:
                    asyncio.create_task(container.telegram_bot.trigger_graceful_server_restart())
                else:
                    asyncio.get_running_loop().call_later(0.6, lambda: os.kill(os.getpid(), signal.SIGTERM))
                return {"ok": True, "message": "Сервер перезавантажується (3 сек)..."}
    except Exception:
        pass


async def build_application_container(
    base_dir: str,
    storage_dir: str,
    wakeup_event: asyncio.Event,
    logger: logging.Logger,
) -> ApplicationContainer:
    event_bus.bind_wakeup_event(wakeup_event)
    _register_restart_endpoint()
    container = ApplicationContainer(logger=logger)
    await container.init_all()
    return container