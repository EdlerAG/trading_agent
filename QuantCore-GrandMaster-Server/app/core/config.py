import os
import secrets
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

RISK_PROFILES_MAP: Dict[str, Tuple[float, float, float]] = {
    "CONSERVATIVE": (0.75, 2.00, 0.25),
    "OPTIMAL":      (1.00, 3.00, 0.25),
    "AGGRESSIVE":   (1.15, 3.50, 0.25),
    "OVERDRIVE":    (1.25, 3.50, 0.25),
}

# (min_qty, step_size, min_notional, tier_role, base_weight)
SYMBOL_SPECS: Dict[str, Tuple[float, float, float, int, float]] = {
    "BTCUSDT":      (0.001, 0.001, 100.0, 1, 1.22),
    "ETHUSDT":      (0.01,  0.01,  20.0,  1, 1.22),
    "SOLUSDT":      (0.1,   0.1,   5.0,   1, 1.20),
    "BNBUSDT":      (0.01,  0.01,  5.0,   3, 0.50),   # Quarantined in longs
    "XRPUSDT":      (1.0,   1.0,   5.0,   2, 0.95),
    "DOGEUSDT":     (10.0,  1.0,   5.0,   2, 0.85),
    "ADAUSDT":      (1.0,   1.0,   5.0,   2, 0.85),
    "AVAXUSDT":     (1.0,   1.0,   5.0,   2, 1.05),
    "LINKUSDT":     (0.1,   0.1,   5.0,   2, 1.15),
    "SUIUSDT":      (1.0,   1.0,   5.0,   2, 1.15),
    "NEARUSDT":     (1.0,   1.0,   5.0,   1, 1.20),
    "FETUSDT":      (1.0,   1.0,   5.0,   3, 0.22),   # Quarantined in longs
    "APTUSDT":      (0.1,   0.1,   5.0,   2, 0.95),
    "ARBUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "INJUSDT":      (0.1,   0.1,   5.0,   2, 0.95),
    "WIFUSDT":      (0.1,   0.1,   5.0,   2, 0.90),
    "1000PEPEUSDT": (1.0,   1.0,   5.0,   2, 0.90),
    "TIAUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "SEIUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "RENDERUSDT":   (0.1,   0.1,   5.0,   2, 0.95),
    "RUNEUSDT":     (1.0,   1.0,   5.0,   2, 0.90),
    "OPUSDT":       (0.1,   0.1,   5.0,   2, 0.90),
    "AAVEUSDT":     (0.1,   0.1,   5.0,   2, 1.00),
    "ORDIUSDT":     (0.1,   0.1,   5.0,   2, 0.90),
    "PENDLEUSDT":   (1.0,   1.0,   5.0,   2, 0.90),
    # Додаткові ліквідні пари UNIVERSE_32 для V2 (перевірені через fapi/v1/exchangeInfo)
    "TRXUSDT":      (1.0,   1.0,   5.0,   2, 1.00),
    "LTCUSDT":      (0.001, 0.001, 20.0,  2, 1.00),
    "BCHUSDT":      (0.001, 0.001, 20.0,  2, 1.00),
    "DOTUSDT":      (0.1,   0.1,   5.0,   2, 0.95),
    "ATOMUSDT":     (0.01,  0.01,  5.0,   2, 0.95),
    "FILUSDT":      (0.1,   0.1,   5.0,   2, 0.95),
    "ETCUSDT":      (0.01,  0.01,  20.0,  2, 0.95),
    "UNIUSDT":      (1.0,   1.0,   5.0,   2, 1.00),
    "LDOUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "CRVUSDT":      (0.1,   0.1,   5.0,   2, 0.90),
    "DYDXUSDT":     (0.1,   0.1,   5.0,   2, 0.90),
    "APEUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    # Додаткові ліквідні пари UNIVERSE_58 для V3 Dataset 2.0
    "1000SHIBUSDT": (1.0,   1.0,   5.0,   2, 0.90),
    "STXUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "IMXUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "GRTUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "ICPUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "HBARUSDT":     (1.0,   1.0,   5.0,   2, 0.90),
    "VETUSDT":      (1.0,   1.0,   5.0,   2, 0.90),
    "ALGOUSDT":     (0.1,   0.1,   5.0,   2, 0.90),
    "SANDUSDT":     (1.0,   1.0,   5.0,   2, 0.85),
    "MANAUSDT":     (1.0,   1.0,   5.0,   2, 0.85),
    "AXSUSDT":      (1.0,   1.0,   5.0,   2, 0.85),
    "GALAUSDT":     (1.0,   1.0,   5.0,   2, 0.85),
    "CHZUSDT":      (1.0,   1.0,   5.0,   2, 0.85),
    "SNXUSDT":      (0.1,   0.1,   5.0,   2, 0.85),
    "COMPUSDT":     (0.001, 0.001, 5.0,   2, 0.90),
    "EGLDUSDT":     (0.1,   0.1,   5.0,   2, 0.85),
    "FLOWUSDT":     (0.1,   0.1,   5.0,   2, 0.85),
    "KAVAUSDT":     (0.1,   0.1,   5.0,   2, 0.85),
    "ROSEUSDT":     (1.0,   1.0,   5.0,   2, 0.85),
    "ENJUSDT":      (1.0,   1.0,   5.0,   2, 0.85),
    "1INCHUSDT":    (1.0,   1.0,   5.0,   2, 0.85),
    "CFXUSDT":      (1.0,   1.0,   5.0,   2, 0.85),
    "MINAUSDT":     (1.0,   1.0,   5.0,   2, 0.85),
    "BLURUSDT":     (1.0,   1.0,   5.0,   2, 0.85),
}

TICK_SIZE_MAP: Dict[str, float] = {
    "BTCUSDT": 0.1, "ETHUSDT": 0.01, "BNBUSDT": 0.01, "LTCUSDT": 0.01, "BCHUSDT": 0.01,
    "COMPUSDT": 0.01, "SOLUSDT": 0.01, "AAVEUSDT": 0.01, "AVAXUSDT": 0.001, "LINKUSDT": 0.001,
    "INJUSDT": 0.001, "APTUSDT": 0.001, "DOTUSDT": 0.001, "ATOMUSDT": 0.001, "FILUSDT": 0.001,
    "ETCUSDT": 0.001, "UNIUSDT": 0.001, "NEARUSDT": 0.001, "ICPUSDT": 0.001, "EGLDUSDT": 0.001,
}


V58_DEFAULT_SYMBOLS_CSV = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,SUIUSDT,"
    "NEARUSDT,FETUSDT,APTUSDT,ARBUSDT,INJUSDT,WIFUSDT,1000PEPEUSDT,TIAUSDT,SEIUSDT,"
    "RENDERUSDT,RUNEUSDT,OPUSDT,AAVEUSDT,ORDIUSDT,PENDLEUSDT"
)

UNIVERSE_32_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "SUIUSDT", "NEARUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "INJUSDT", "AAVEUSDT",
    "TRXUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT",
    "ATOMUSDT", "FILUSDT", "ETCUSDT", "UNIUSDT",
    "LDOUSDT", "CRVUSDT", "DYDXUSDT", "APEUSDT",
    "FETUSDT", "TIAUSDT", "SEIUSDT", "PENDLEUSDT",
)

UNIVERSE_58_SYMBOLS: Tuple[str, ...] = UNIVERSE_32_SYMBOLS + (
    "1000PEPEUSDT", "1000SHIBUSDT", "RUNEUSDT", "STXUSDT",
    "IMXUSDT", "GRTUSDT", "ICPUSDT", "HBARUSDT",
    "VETUSDT", "ALGOUSDT", "SANDUSDT", "MANAUSDT",
    "AXSUSDT", "GALAUSDT", "CHZUSDT", "SNXUSDT",
    "COMPUSDT", "EGLDUSDT", "FLOWUSDT", "KAVAUSDT",
    "ROSEUSDT", "ENJUSDT", "1INCHUSDT", "CFXUSDT",
    "MINAUSDT", "BLURUSDT",
)


def _resolve_default_symbols() -> Tuple[str, ...]:
    raw_env = os.getenv("ACTIVE_SYMBOLS", "").strip()
    if raw_env:
        return tuple(s.strip().upper() for s in raw_env.split(",") if s.strip())
    eng = os.getenv("CARTRIDGE_ENGINE", "v58").strip().lower()
    if eng in ("v3", "v4", "v5", "v6", "qv3", "qv3_convex"):
        return UNIVERSE_58_SYMBOLS
    if eng == "v2":
        return UNIVERSE_32_SYMBOLS
    return tuple(s.strip().upper() for s in V58_DEFAULT_SYMBOLS_CSV.split(",") if s.strip())


def symbol_to_ccxt(binance_sym: str) -> str:
    clean = binance_sym.upper().replace("/", "").replace(":USDT", "")
    if clean.endswith("USDT"):
        return f"{clean[:-4]}/USDT:USDT"
    return f"{clean}/USDT:USDT"


def ccxt_to_symbol(ccxt_sym: str) -> str:
    return ccxt_sym.upper().split(":")[0].replace("/", "")


@dataclass(frozen=True, slots=True)
class Settings:
    PROJECT_NAME: str = "QuantCore Sovereign Server"
    VERSION: str = "58.0-PureSOTA"

    BASE_DIR: str = BASE_DIR
    STORAGE_DIR: str = os.path.join(BASE_DIR, "storage")
    CARTRIDGES_DIR: str = os.path.join(BASE_DIR, "storage", "cartridges")
    BACKUPS_DIR: str = os.path.join(BASE_DIR, "storage", "backups")
    V2_TELEMETRY_DIR: str = os.path.join(BASE_DIR, "storage", "v2_telemetry")
    MARKET_CACHE_DIR: str = os.path.join(BASE_DIR, "storage", "market_cache")
    HEARTBEAT_FILE: str = os.path.join(BASE_DIR, "storage", "heartbeat.json")
    DB_PATH: str = os.path.join(BASE_DIR, "storage", "trading_history.db")
    LOG_PATH: str = os.path.join(BASE_DIR, "storage", "trading_bot.log")
    STATE_FILE: str = os.path.join(BASE_DIR, "storage", "engine_state.json")
    ONLINE_LEARNING_FILE: str = os.path.join(BASE_DIR, "storage", "adaptive_weights.json")

    BINANCE_API_KEY: str = os.getenv("TESTNET_API_KEY", "")
    BINANCE_SECRET_KEY: str = os.getenv("TESTNET_SECRET_KEY", "")
    USE_DEMO_TRADING: bool = os.getenv("USE_DEMO_TRADING", "true").lower() == "true"
    EXCHANGE_LEVERAGE: int = int(os.getenv("EXCHANGE_LEVERAGE", "10"))

    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    ENABLE_NEWS_SENTIMENT: bool = os.getenv(
        "ENABLE_NEWS_SENTIMENT",
        "false" if os.getenv("CARTRIDGE_ENGINE", "v58").strip().lower() in ("v2", "v3", "v4", "v5", "v6", "qv3", "qv3_convex") else "true",
    ).lower() == "true"
    NEWS_REQUEST_TIMEOUT: int = 10

    DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "http://localhost:8501").rstrip("/")
    DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD") or secrets.token_hex(24)
    DASHBOARD_VIEW_PASSWORD: str = os.getenv("DASHBOARD_VIEW_PASSWORD", "").strip()
    DASHBOARD_ADMIN_KEY_FILE: str = os.getenv("DASHBOARD_ADMIN_KEY_FILE", os.path.join(BASE_DIR, ".admin_key"))
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8501"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    ENABLE_API_DOCS: bool = os.getenv("ENABLE_API_DOCS", "false").lower() in ("1", "true", "yes")
    ALLOW_CARTRIDGE_UPLOAD: bool = os.getenv("ALLOW_CARTRIDGE_UPLOAD", "true").lower() in ("1", "true", "yes")
    ALLOW_QUERY_KEY_AUTH: bool = os.getenv("ALLOW_QUERY_KEY_AUTH", "false").lower() in ("1", "true", "yes")

    DEFAULT_RISK_PROFILE: str = os.getenv("RISK_PROFILE", "OPTIMAL").upper()
    DEFAULT_ORCHESTRATOR_MODE: str = os.getenv("ORCHESTRATOR_MODE", "PORTFOLIO_SYNERGY").upper()
    ENABLE_ONLINE_LEARNING: bool = os.getenv(
        "ENABLE_ONLINE_LEARNING",
        "false" if os.getenv("CARTRIDGE_ENGINE", "v58").strip().lower() in ("v2", "v3", "v4", "v5", "v6", "qv3", "qv3_convex") else "true",
    ).lower() == "true"

    CANDLES_FETCH_LIMIT: int = 1950
    # V2: ядро рахує 1h-фічі. V58 очікує 15m, тому дефолт лишається 15m.
    # Для V2: CANDLE_TIMEFRAME=1h, CANDLE_INTERVAL_MINUTES=60, CARTRIDGE_ENGINE=v2.
    CANDLE_TIMEFRAME: str = os.getenv("CANDLE_TIMEFRAME", "15m").strip().lower()
    CANDLE_INTERVAL_MINUTES: int = int(
        os.getenv(
            "CANDLE_INTERVAL_MINUTES",
            "60" if os.getenv("CANDLE_TIMEFRAME", "15m").strip().lower() == "1h" else "15",
        )
    )
    CARTRIDGE_ENGINE: str = os.getenv("CARTRIDGE_ENGINE", "v58").strip().lower()
    FUNDING_HISTORY_HOURS: int = int(os.getenv("FUNDING_HISTORY_HOURS", "720"))
    CASH_ZONE_THRESHOLD: float = 0.015
    ACTION_DEADZONE: float = float(os.getenv("ACTION_DEADZONE", "0.10"))
    STICKY_RANK_BONUS: float = 0.05

    MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.05"))
    MAX_TOTAL_DRAWDOWN_PCT: float = float(os.getenv("MAX_TOTAL_DRAWDOWN_PCT", "0.20"))
    MAX_GROSS_LEVERAGE_CAP: float = float(os.getenv("MAX_GROSS_LEVERAGE_CAP", "2.25"))
    MAX_ALLOWED_SPREAD_PCT: float = float(os.getenv("MAX_ALLOWED_SPREAD_PCT", "0.0055"))
    PROTECTED_IOC_MAX_SLIP_PCT: float = float(os.getenv("PROTECTED_IOC_MAX_SLIP_PCT", "0.0025"))
    MAX_FUNDING_RATE: float = 0.0005
    MAX_ADVERSE_FUNDING_BLEED: float = float(os.getenv("MAX_ADVERSE_FUNDING_BLEED", "0.0030"))
    FUNDING_BUFFER_MINUTES: int = 15
    MAKER_TIMEOUT_SEC: int = 9
    V2_MAKER_WAIT_SEC: float = float(os.getenv("V2_MAKER_WAIT_SEC", "3.5"))
    V3_URGENT_MAKER_WAIT_SEC: float = float(os.getenv("V3_URGENT_MAKER_WAIT_SEC", "1.8"))
    V3_SHORT_SQUEEZE_ATR_MULT: float = float(os.getenv("V3_SHORT_SQUEEZE_ATR_MULT", "4.8"))
    V6_LONG_CRASH_ATR_MULT: float = float(os.getenv("V6_LONG_CRASH_ATR_MULT", "12.0"))
    ENABLE_V3_AUX_CHANNELS: bool = os.getenv("ENABLE_V3_AUX_CHANNELS", "true").lower() == "true"
    VIRTUAL_EQUITY_CAP: float = float(os.getenv("VIRTUAL_EQUITY_CAP", "0.0") or "0.0")
    ENABLE_SHADOW_ARENA: bool = os.getenv(
        "ENABLE_SHADOW_ARENA",
        "false" if os.getenv("CARTRIDGE_ENGINE", "v58").strip().lower() in ("v6", "qv3", "qv3_convex") else "true",
    ).lower() == "true"
    ENABLE_WS_SENTINEL: bool = os.getenv(
        "ENABLE_WS_SENTINEL",
        "true" if os.getenv("WS_SENTINEL_OBSERVE_ONLY", "true").lower() == "true" else (
            "false" if os.getenv("CARTRIDGE_ENGINE", "v58").strip().lower() in ("v2", "v3", "v4", "v5", "v6", "qv3", "qv3_convex") else "true"
        ),
    ).lower() == "true"
    WS_SENTINEL_OBSERVE_ONLY: bool = os.getenv("WS_SENTINEL_OBSERVE_ONLY", "true").lower() == "true"
    WS_SENTINEL_SAMPLE_SEC: float = float(os.getenv("WS_SENTINEL_SAMPLE_SEC", "5.0"))
    MAX_MARKET_CACHE_MB: int = int(os.getenv("MAX_MARKET_CACHE_MB", "200"))
    SL_COOLDOWN_HOURS: int = int(os.getenv("SL_COOLDOWN_HOURS", "48"))
    NTP_WARN_THRESHOLD_MS: int = int(os.getenv("NTP_WARN_THRESHOLD_MS", "150"))
    ENABLE_V3_RESEARCH_LAKE: bool = os.getenv("ENABLE_V3_RESEARCH_LAKE", "true").lower() == "true"
    V3_RESEARCH_LAKE_DIR: str = os.getenv("V3_RESEARCH_LAKE_DIR", os.path.join(BASE_DIR, "data", "v3_research_lake"))
    MAX_RESEARCH_LAKE_MB: int = int(os.getenv("MAX_RESEARCH_LAKE_MB", "1024"))
    ENABLE_SMART_MAKER_CHASE: bool = os.getenv("ENABLE_SMART_MAKER_CHASE", "false").lower() == "true"
    SMART_MAKER_MAX_RETRIES: int = int(os.getenv("SMART_MAKER_MAX_RETRIES", "3"))
    SMART_MAKER_REQUOTE_SEC: float = float(os.getenv("SMART_MAKER_REQUOTE_SEC", "2.5"))
    MAX_CANDLE_STALENESS_MULT: float = float(os.getenv("MAX_CANDLE_STALENESS_MULT", "1.8"))
    NEUTRALITY_IMBALANCE_LIMIT: float = float(os.getenv("NEUTRALITY_IMBALANCE_LIMIT", "0.05"))
    MAX_NTP_CLOCK_SKEW_MS: int = int(os.getenv("MAX_NTP_CLOCK_SKEW_MS", "1000"))
    DELISTING_BUFFER_HOURS: float = float(os.getenv("DELISTING_BUFFER_HOURS", "72.0"))
    POSITION_DRIFT_ALERT_PCT: float = float(os.getenv("POSITION_DRIFT_ALERT_PCT", "0.01"))
    EXTERNAL_HEARTBEAT_URL: str = os.getenv("EXTERNAL_HEARTBEAT_URL", "").strip()
    STRICT_STARTUP_PREFLIGHT: bool = os.getenv("STRICT_STARTUP_PREFLIGHT", "true").lower() == "true"

    # V58.0 Breakthrough: Intra-Candle ATR Stop-Loss & Sub-Candle MFE Harvester
    EMERGENCY_SL_ATR_MULT: float = 1.35
    SUB_CANDLE_MFE_ATR_MULT: float = 1.35
    ATR_BREAKEVEN_TRIGGER: float = 1.20
    BREAKEVEN_BUFFER_PCT: float = 0.0007

    MAX_STORAGE_MB: int = int(os.getenv("MAX_STORAGE_MB", "250"))
    MAX_STORAGE_BYTES: int = int(os.getenv("MAX_STORAGE_MB", "250")) * 1024 * 1024
    MAX_CARTRIDGES_KEPT: int = 2
    MAX_BACKUPS_KEPT: int = 3
    DB_RETENTION_DAYS: int = 60

    DEFAULT_SYMBOLS: Tuple[str, ...] = field(default_factory=_resolve_default_symbols)

    def get_symbol_spec(self, sym: str) -> Tuple[float, float, float, int, float]:
        clean = ccxt_to_symbol(sym)
        return SYMBOL_SPECS.get(clean, (0.001, 0.001, 5.0, 2, 0.85))

    def get_tick_size(self, sym: str) -> float:
        clean = ccxt_to_symbol(sym)
        return TICK_SIZE_MAP.get(clean, 0.0001)

    @property
    def effective_candles_limit(self) -> int:
        # Для 1h V6 потрібно >= 720 барів для 30-денної Shrunk Downside Beta та Ledoit-Wolf sigma_30d (820 вміщується в 1 сторінку REST!).
        if self.CARTRIDGE_ENGINE in ("v2", "v3", "v4", "v5", "v6", "qv3", "qv3_convex") and self.CANDLE_TIMEFRAME == "1h":
            return int(os.getenv("V2_CANDLES_FETCH_LIMIT", "820"))
        return self.CANDLES_FETCH_LIMIT


settings = Settings()

for _d in (settings.STORAGE_DIR, settings.CARTRIDGES_DIR, settings.BACKUPS_DIR, settings.V2_TELEMETRY_DIR, settings.MARKET_CACHE_DIR):
    os.makedirs(_d, exist_ok=True)
