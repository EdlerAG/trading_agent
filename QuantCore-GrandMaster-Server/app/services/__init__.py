"""Domain microservices: State, Online Self-Learning, SQLite WAL, CCXT Multi-Asset, Execution, Telegram OTA Bot."""

from app.services.service_registry import ApplicationContainer, build_application_container

__all__ = ["ApplicationContainer", "build_application_container"]