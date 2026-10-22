from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
import pandas as pd
from app.domain.schemas import (
    CoinStateDTO,
    PortfolioTargetDTO,
    ExchangePositionDTO,
    OrderExecutionDTO,
)


class IService(ABC):
    """
    Базовий контракт мікросервісу (за зразком IService.h у SmartLamp).
    Кожен сервіс має чітку назву, ініціалізацію та коректне завершення.
    """
    __slots__ = ()

    @property
    @abstractmethod
    def name(self) -> str:
        """Унікальне ім'я мікросервісу."""

    @abstractmethod
    async def init(self) -> None:
        """Ініціалізація ресурсів під час старту сервера."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Безпечне звільнення ресурсів та збереження стану при зупинці."""


class IAlphaCartridge(ABC):
    """
    Універсальний контракт Картриджа Моделі ШІ (Open/Closed Principle).
    Будь-яка майбутня модель (QuantCore V58 Pure SOTA)
    реалізує цей інтерфейс. Сервер викликає лише compute_portfolio_targets()
    і не залежить від внутрішньої математики моделі!
    """
    __slots__ = ()

    @property
    @abstractmethod
    def architecture_name(self) -> str:
        """Назва архітектури бандла (напр. 'QuantCore_V58_0_Pure_SOTA_Production')."""

    @property
    @abstractmethod
    def supported_symbols(self) -> Tuple[str, ...]:
        """Перелік валют, які підтримує цей картридж."""

    @abstractmethod
    def compute_portfolio_targets(
        self,
        candles_map: Dict[str, pd.DataFrame],
        coin_states: Dict[str, CoinStateDTO],
        online_weights: Dict[str, Dict[str, Any]],
        max_portfolio_lev: float,
        orchestrator_mode: str,
        news_sentiment: float = 0.0,
    ) -> PortfolioTargetDTO:
        """
        Приймає свічки всіх активних монет, поточні стани позицій та онлайн-ваги самонавчання,
        і повертає готовий, збалансований портфель цільових ваг PortfolioTargetDTO.
        """


class IExchangeGateway(IService):
    """Абстрактний контракт біржового шлюзу (дозволяє легко міняти Binance Demo / Live / Bybit)."""
    __slots__ = ()

    @abstractmethod
    async def fetch_account_snapshot(self, symbols: Tuple[str, ...]) -> Tuple[float, float, Dict[str, ExchangePositionDTO], bool]:
        """
        Повертає: (usdt_wallet_balance, total_unrealized_pnl, positions_by_symbol, is_ok).
        Ніколи не повертає фейковий 0.0 при тимчасовому обриві мережі (is_ok=False).
        """

    @abstractmethod
    async def fetch_delta_candles(self, symbol: str, limit: int) -> Optional[pd.DataFrame]:
        """Повертає 15m свічки з Ring-Buffer кешем (довантажуючи лише нові бари)."""

    @abstractmethod
    async def fetch_funding_rates(self, symbols: Tuple[str, ...]) -> Dict[str, float]:
        """Отримує актуальні ставки фінансування (funding rates) для переліку символів."""

    @abstractmethod
    async def execute_smart_rebalance_order(
        self,
        symbol: str,
        delta_qty: float,
        mark_price: float,
        realized_pnl_est: float = 0.0,
        note: str = "",
        reduce_only: bool = False,
    ) -> Optional[OrderExecutionDTO]:
        """Виконує ордер за алгоритмом Maker Post-Only -> Market Fallback."""

    @abstractmethod
    async def place_or_update_stop_loss(
        self,
        symbol: str,
        position_qty: float,
        stop_price: float,
    ) -> bool:
        """Надійно виставляє або оновлює біржовий STOP_MARKET (MARK_PRICE) на весь об'єм позиції."""

    @abstractmethod
    async def place_or_update_take_profit(
        self,
        symbol: str,
        position_qty: float,
        tp_price: float,
    ) -> bool:
        """Виставляє біржовий TAKE_PROFIT_MARKET ордер для реалізації Sub-Candle MFE Harvester."""

    @abstractmethod
    async def place_passive_stink_bid(self, symbol: str, qty: float, price: float) -> Optional[str]:
        """Виставляє пасивний Post-Only лімітний ордер (Stink-Bid) для збору ліквідаційного проколу."""

    @abstractmethod
    async def cancel_symbol_orders(self, symbol: str) -> bool:
        """Скасовує всі активні лімітні, стоп та тейк-профіт ордери по конкретній валюті."""

    @abstractmethod
    async def emergency_liquidate_all(self, symbols: Tuple[str, ...]) -> str:
        """Негайно скасовує всі ордери та закриває всі відкриті позиції в USDT за ринком."""


class IOnlineLearner(IService):
    """Контракт модуля безперервного онлайн-самонавчання в реальному часі."""
    __slots__ = ()

    @abstractmethod
    def get_asset_learning_state(self, symbol: str) -> Dict[str, Any]:
        """Повертає поточні онлайн-ваги (online_mult, bandit_weights, pod_dd) для монети."""

    @abstractmethod
    def record_step_and_adapt(
        self,
        symbol: str,
        prev_price: float,
        curr_price: float,
        prev_model_pos: float,
        tier_role: int,
        new_submodel_preds: Optional[List[float]] = None,
    ) -> float:
        """Фіксує крок ціни та адаптує онлайн-ваги MWU/Bandit для монети."""

    @abstractmethod
    def get_all_learning_states(self) -> Dict[str, Dict[str, Any]]:
        """Повертає онлайн-ваги по всіх монетах."""

    @abstractmethod
    def save_state(self) -> None:
        """Атомарно зберігає стан самонавчання на диск."""
