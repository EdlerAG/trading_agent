from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


# =====================================================================
# 1. ВНУТРІШНІ ШВИДКІ DTO З __SLOTS__ (ZERO-OVERHEAD MEMORY)
# =====================================================================
@dataclass(slots=True)
class ExchangePositionDTO:
    """Фактичний стан позиції конкретної монети на біржі Binance Futures."""
    symbol: str
    contracts_qty: float = 0.0      # Додатне для Long, від'ємне для Short
    entry_price: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    notional_usdt: float = 0.0


@dataclass(slots=True)
class CoinStateDTO:
    """Повний стан та налаштування керування однією валютою в пам'яті."""
    symbol: str
    enabled: bool = True
    mode: int = 1                   # CoinMode (1=AUTO, 2=LONG_ONLY, 0=OFF...)
    tier_role: int = 1              # TierRole (1=CORE, 2=MAJOR, 3=SATELLITE)
    base_weight: float = 1.0
    max_long_lev: float = 2.40
    max_short_lev: float = 1.25
    current_pos_qty: float = 0.0
    entry_price: float = 0.0
    active_sl_price: float = 0.0
    is_breakeven: bool = False
    bars_held: int = 0
    phase: int = 0
    last_signal: float = 0.0
    alpha_score: float = 0.0
    mwu_trust: float = 1.05


@dataclass(slots=True)
class CoinTargetDTO:
    """Універсальний вихід картриджа ШІ по одній монеті (незалежно від версії моделі V7..V30)."""
    symbol: str
    desired_weight: float           # Цільова частка від загального Equity (напр. +0.85x або -0.45x)
    raw_model_pos: float            # Сира позиція каскаду монети до портфельного масштабування
    phase: int                      # CascadePhase (-1..3)
    alpha_score: float              # Інтегральний бал сили монети
    signal_macro: float             # Сигнал макро-ядра
    signal_ml: float                # Сигнал ML-стекера
    ker_purity: float               # Чистота тренду Кауфмана (KER)
    zscore_96: float                # 24h Z-Score
    rs_vs_btc: float                # Відносна сила проти BTC
    current_price: float            # Поточна ціна закриття
    atr_14: float                   # Волатильність ATR для розрахунку страхового Stop-Loss
    raw_submodel_preds: Optional[List[float]] = None  # Сирі прогнози під-моделей для онлайн-самонавчання


@dataclass(slots=True)
class PortfolioTargetDTO:
    """
    Єдиний стандартизований вихід будь-якого картриджа моделі (IAlphaCartridge).
    Завдяки цьому контракту сервер ніколи не потрібно переписувати при зміні логіки моделі!
    """
    cartridge_name: str
    architecture: str
    candle_timestamp: str
    market_breadth: float
    news_sentiment: float
    total_gross_leverage: float
    net_leverage: float
    targets: Dict[str, CoinTargetDTO] = field(default_factory=dict)
    extra_telemetry: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderExecutionDTO:
    """Результат фактичного виконання біржового ордера (Maker Post-Only / Market)."""
    symbol: str
    side: str                       # 'BUY' або 'SELL'
    executed_qty: float
    avg_price: float
    fee_usdt: float
    realized_pnl_est: float
    order_id: Optional[str] = None
    note: str = ""


# =====================================================================
# 2. PYDANTIC V2 СХЕМИ ДЛЯ REST API ТА ВЕБ-ТЕРМІНАЛУ
# =====================================================================
class AuthLoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=64)


class CoinControlUpdateRequest(BaseModel):
    symbol: str = Field(..., min_length=5, max_length=16, description="Наприклад BTCUSDT")
    enabled: Optional[bool] = None
    mode: Optional[int] = Field(None, ge=0, le=4, description="0=OFF, 1=AUTO, 2=LONG_ONLY, 3=SHORT_ONLY, 4=CORE_ONLY")
    base_weight: Optional[float] = Field(None, ge=0.10, le=2.50)
    max_long_lev: Optional[float] = Field(None, ge=0.20, le=3.50)
    max_short_lev: Optional[float] = Field(None, ge=0.00, le=2.50)


class RiskProfileUpdateRequest(BaseModel):
    risk_profile: str = Field(..., description="CONSERVATIVE | OPTIMAL | AGGRESSIVE | OVERDRIVE")
    orchestrator_mode: Optional[str] = Field(None, description="PORTFOLIO_SYNERGY | SOLO_MAX")


class PauseControlRequest(BaseModel):
    paused: bool
    hours: Optional[float] = Field(None, ge=0.0, le=168.0)


class CartridgeSelectRequest(BaseModel):
    filename: str = Field(..., min_length=5, max_length=120)