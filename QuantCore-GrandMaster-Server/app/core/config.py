import os
from dataclasses import dataclass, field
from typing import Dict, Tuple


def _load_dotenv_file(env_path: str) -> None:
    """Надлегкий парсер .env без зовнішніх алокацій."""
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_load_dotenv_file(os.path.join(BASE_DIR, ".env"))

# Профілі ризику: (Базовий множник, Макс. плече портфеля, Deadzone)
RISK_PROFILES_MAP: Dict[str, Tuple[float, float, float]] = {
    "CONSERVATIVE": (0.75, 1.60, 0.25),  # Мінімальна просадка
    "OPTIMAL":      (1.00, 2.40, 0.25),  # Calmar 10.35 Champion (+187.4% OOS)
    "AGGRESSIVE":   (1.15, 3.20, 0.25),  # High-Octane (+226.4% OOS)
    "OVERDRIVE":    (1.25, 3.50, 0.25),  # Grand-Master Overdrive (+264.8% OOS)
}

# Специфікація точності та мінімальних лімітів для Binance Futures USDT-M
# (min_qty, step_size, min_notional_usdt, default_tier_role, default_base_weight)
SYMBOL_SPECS: Dict[str, Tuple[float, float, float, int, float]] = {
    "BTCUSDT":  (0.001, 0.001, 5.0, 1, 1.22),
    "ETHUSDT":  (0.005, 0.001, 5.0, 1, 1.22),
    "SOLUSDT":  (0.1,   0.1,   5.0, 1, 1.12),
    "BNBUSDT":  (0.01,  0.01,  5.0, 2, 0.90),
    "XRPUSDT":  (4.0,   0.1,   5.0, 2, 0.95),
    "DOGEUSDT": (40.0,  1.0,   5.0, 3, 0.50),
    "AVAXUSDT": (0.2,   0.1,   5.0, 2, 0.85),
    "LINKUSDT": (0.4,   0.1,   5.0, 2, 0.85),
}


def symbol_to_ccxt(binance_sym: str) -> str:
    """Конвертує 'BTCUSDT' -> 'BTC/USDT:USDT' для CCXT Futures."""
    clean = binance_sym.upper().replace("/", "").replace(":USDT", "")
    if clean.endswith("USDT"):
        base = clean[:-4]
        return f"{base}/USDT:USDT"
    return f"{clean}/USDT:USDT"


def ccxt_to_symbol(ccxt_sym: str) -> str:
    """Конвертує 'BTC/USDT:USDT' -> 'BTCUSDT'."""
    return ccxt_sym.upper().split(":")[0].replace("/", "")


@dataclass(frozen=True, slots=True)
class Settings:
    PROJECT_NAME: str = "QuantCore Grand-Master Server"
    VERSION: str = "23.0-GrandMaster"

    # Базові директорії та файли у storage/
    BASE_DIR: str = BASE_DIR
    STORAGE_DIR: str = os.path.join(BASE_DIR, "storage")
    CARTRIDGES_DIR: str = os.path.join(BASE_DIR, "storage", "cartridges")
    BACKUPS_DIR: str = os.path.join(BASE_DIR, "storage", "backups")
    DB_PATH: str = os.path.join(BASE_DIR, "storage", "trading_history.db")
    LOG_PATH: str = os.path.join(BASE_DIR, "storage", "trading_bot.log")
    STATE_FILE: str = os.path.join(BASE_DIR, "storage", "engine_state.json")
    ONLINE_LEARNING_FILE: str = os.path.join(BASE_DIR, "storage", "online_learning.json")

    # Ключі авторизації (сумісні зі старим .env)
    BINANCE_API_KEY: str = os.getenv("TESTNET_API_KEY", "")
    BINANCE_SECRET_KEY: str = os.getenv("TESTNET_SECRET_KEY", "")
    USE_DEMO_TRADING: bool = os.getenv("USE_DEMO_TRADING", "true").lower() == "true"
    EXCHANGE_LEVERAGE: int = int(os.getenv("EXCHANGE_LEVERAGE", "3"))

    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    ENABLE_NEWS_SENTIMENT: bool = os.getenv("ENABLE_NEWS_SENTIMENT", "true").lower() == "true"
    NEWS_REQUEST_TIMEOUT: int = 10

    DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "http://localhost:8501").rstrip("/")
    DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "0511")
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8501"))

    # Налаштування мультивалютного ядра та ризику
    DEFAULT_RISK_PROFILE: str = os.getenv("RISK_PROFILE", "OPTIMAL").upper()
    DEFAULT_ORCHESTRATOR_MODE: str = os.getenv("ORCHESTRATOR_MODE", "PORTFOLIO_SYNERGY").upper()
    ENABLE_ONLINE_LEARNING: bool = os.getenv("ENABLE_ONLINE_LEARNING", "true").lower() == "true"

    CANDLES_FETCH_LIMIT: int = 1950  # Достатньо для EMA-1536 + EWM хвоста (економить 35% RAM проти 2600)
    CASH_ZONE_THRESHOLD: float = 0.06
    ACTION_DEADZONE: float = 0.25
    STICKY_RANK_BONUS: float = 0.03

    # Ліміти безпеки та виконання (CRO Shield)
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.06"))
    MAX_ALLOWED_SPREAD_PCT: float = 0.0010
    MAX_FUNDING_RATE: float = 0.0005
    FUNDING_BUFFER_MINUTES: int = 15
    MAKER_TIMEOUT_SEC: int = 18

    EMERGENCY_SL_ATR_MULT: float = 3.5
    ATR_BREAKEVEN_TRIGGER: float = 1.8
    BREAKEVEN_BUFFER_PCT: float = 0.0007

    # Обмеження диска та пам'яті для малого VPS (1GB RAM)
    MAX_STORAGE_MB: int = int(os.getenv("MAX_STORAGE_MB", "250"))
    MAX_STORAGE_BYTES: int = int(os.getenv("MAX_STORAGE_MB", "250")) * 1024 * 1024
    MAX_CARTRIDGES_KEPT: int = 2     # Активний картридж + 1 попередній для миттєвого Rollback
    MAX_BACKUPS_KEPT: int = 3        # Не більше 3 архівних бекапів БД на диску
    DB_RETENTION_DAYS: int = 60      # Авто-очищення старих свічок у SQLite старше 60 діб

    DEFAULT_SYMBOLS: Tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip().upper()
            for s in os.getenv("ACTIVE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT").split(",")
            if s.strip()
        )
    )

    def get_symbol_spec(self, sym: str) -> Tuple[float, float, float, int, float]:
        clean = ccxt_to_symbol(sym)
        return SYMBOL_SPECS.get(clean, (0.001, 0.001, 5.0, 2, 0.85))


settings = Settings()

for _d in (settings.STORAGE_DIR, settings.CARTRIDGES_DIR, settings.BACKUPS_DIR):
    os.makedirs(_d, exist_ok=True)