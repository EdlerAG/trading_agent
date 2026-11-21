import asyncio
import time
from enum import StrEnum
from typing import Callable, Dict, List, Any, Optional, Awaitable


class EventType(StrEnum):
    FORCE_RECALC = "FORCE_RECALC"               # Примусовий перерахунок свічки
    CARTRIDGE_HOT_SWAPPED = "CARTRIDGE_SWAPPED" # Завантажено нову модель .joblib
    RISK_PROFILE_CHANGED = "RISK_CHANGED"       # Зміна профілю (1.6x / 2.4x / 3.2x / 3.5x)
    COIN_CONFIG_CHANGED = "COIN_CHANGED"        # Зміна режиму конкретної валюти (AUTO / LONG_ONLY / OFF)
    CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER" # Аварійне спрацювання захисту просадки
    PANIC_CLOSE_ALL = "PANIC_CLOSE_ALL"         # Негайна ліквідація всіх позицій у кеш USDT
    TELEGRAM_ALERT = "TELEGRAM_ALERT"           # Відправка повідомлення в Telegram


class AppEvent:
    __slots__ = ("event_type", "payload", "timestamp")

    def __init__(self, event_type: EventType, payload: Optional[Dict[str, Any]] = None) -> None:
        self.event_type: EventType = event_type
        self.payload: Dict[str, Any] = payload or {}
        self.timestamp: float = time.time()


EventHandler = Callable[[AppEvent], Awaitable[None]]


class AsyncEventBus:
    """Надлегка асинхронна шина подій із підтримкою Wakeup-сигналу для головного циклу."""

    __slots__ = ("_subscribers", "_wakeup_event")

    def __init__(self) -> None:
        self._subscribers: Dict[EventType, List[EventHandler]] = {}
        self._wakeup_event: Optional[asyncio.Event] = None

    def bind_wakeup_event(self, wakeup_ev: asyncio.Event) -> None:
        self._wakeup_event = wakeup_ev

    def trigger_wakeup(self) -> None:
        if self._wakeup_event is not None:
            self._wakeup_event.set()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    async def publish(self, event_type: EventType, payload: Optional[Dict[str, Any]] = None, wake_engine: bool = False) -> None:
        if wake_engine:
            self.trigger_wakeup()

        handlers = self._subscribers.get(event_type)
        if not handlers:
            return

        ev = AppEvent(event_type, payload)
        for handler in handlers:
            try:
                await handler(ev)
            except Exception:
                pass


event_bus = AsyncEventBus()