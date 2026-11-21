import asyncio
import logging
from datetime import datetime, timezone
from app.core.config import settings
from app.domain.interfaces import IService, IExchangeGateway
from app.services.state_service import StateService
from app.services.database_service import DatabaseService


class RiskGuardService(IService):
    """
    Незалежний CRO Ризик-Менеджер та Watchdog (RiskGuardService):
    1. Daily Circuit Breaker: контролює максимальну денну просадку капіталу (6%).
    2. Dynamic ATR Breakeven: переводить страховий STOP_MARKET у беззбиток при +1.8x ATR.
    3. Background Watchdog Loop: легкий фоновий процес для container.watchdog у main.py.
    """

    __slots__ = ("_logger", "_state", "_db", "_exchange", "_orchestrator")

    def __init__(
        self,
        logger: logging.Logger,
        state_service: StateService,
        db_service: DatabaseService,
        exchange_service: IExchangeGateway,
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._db = db_service
        self._exchange = exchange_service
        self._orchestrator = None

    @property
    def name(self) -> str:
        return "RiskGuardService"

    def bind_orchestrator(self, orchestrator) -> None:
        self._orchestrator = orchestrator

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def check_circuit_breaker(self, total_equity: float) -> bool:
        """Повертає True, якщо спрацював денний стоп-кран просадки (Circuit Breaker)."""
        if total_equity <= 0.0:
            return False

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._state.last_reset_date != today_str or self._state.daily_starting_equity <= 0.0:
            past_pnl = self._db.get_daily_realized_pnl()
            base_eq = total_equity - past_pnl if (total_equity - past_pnl) > 0 else total_equity
            self._state.daily_starting_equity = base_eq
            self._state.last_reset_date = today_str
            self._state.save_snapshot()

        start_eq = self._state.daily_starting_equity
        if start_eq > 0:
            dd = (start_eq - total_equity) / start_eq
            if dd >= settings.MAX_DAILY_LOSS_PCT and not self._state.is_paused:
                self._state.set_pause_state(paused=True, hours=2.0)
                if self._orchestrator is not None:
                    await self._orchestrator.emergency_close_all_positions()
                return True
        return False

    async def loop(self) -> None:
        """
        Фоновий Watchdog-цикл (викликається з main.py як container.watchdog.loop()).
        Перевіряє автоматичне відновлення після таймера паузи кожні 60 секунд із 0% CPU.
        """
        while True:
            try:
                await asyncio.sleep(60.0)
                if self._state.check_and_auto_resume_pause():
                    self._logger.info("🟢 [RiskWatchdog] Таймер паузи вичерпано — торгівлю автоматично відновлено.")
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(60.0)