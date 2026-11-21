"""Domain microservices: State, Online Self-Learning, SQLite WAL, CCXT Multi-Asset, Execution, Telegram OTA Bot, WebSocket Sentinel."""

from app.services.service_registry import ApplicationContainer, build_application_container
from app.services.ws_sentinel_service import WebSocketSentinelService

__all__ = ["ApplicationContainer", "build_application_container", "WebSocketSentinelService"]
