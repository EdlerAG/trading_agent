"""Core infrastructure: slotted configuration, RAM/Disk guardian, event bus, security, and HTTP pool."""

from app.core.config import settings
from app.core.memory_guard import memory_guard
from app.core.events import event_bus, EventType
from app.core.http_client import http_pool

__all__ = ["settings", "memory_guard", "event_bus", "EventType", "http_pool"]