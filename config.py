import os

# Жорстке обмеження багатопотоковості C-бібліотек для мінімального споживання RAM/CPU на VPS
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# --- БАЗОВІ ШЛЯХИ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# --- КЛЮЧІ ТА АВТОРИЗАЦІЯ ---
TESTNET_API_KEY = os.getenv("TESTNET_API_KEY")
TESTNET_SECRET_KEY = os.getenv("TESTNET_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8501")

if not all([TESTNET_API_KEY, TESTNET_SECRET_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("❌ Не всі обов'язкові змінні (Binance / Telegram) знайдено у файлі .env!")

# --- ПАРАМЕТРИ ПАРИ ТА МОДЕЛІ QUANTCORE V7.8 ULTRA ---
SYMBOL = 'BTC/USDT:USDT'
BINANCE_PAIR = "BTCUSDT"

MODEL_TYPE = "QUANTCORE_V7_8_ULTRA"
MODEL_NAME = "quant_core_production.joblib"
MODEL_PATH = os.path.join(BASE_DIR, MODEL_NAME)
DB_PATH = os.path.join(BASE_DIR, "trading_history.db")
LOG_PATH = os.path.join(BASE_DIR, "trading_bot.log")
STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")

# --- ПРОФІЛІ РИЗИКУ ТА КАПІТАЛУ ---
RISK_PROFILES_MAP = {
    "CONSERVATIVE": (0.75, 1.00),  # +25.91% Net, MaxDD -12.51%
    "OPTIMAL":      (0.80, 1.30),  # +32.99% Net, MaxDD -15.96% (Рекомендовано)
    "AGGRESSIVE":   (1.00, 1.50)   # +38.14% Net, MaxDD -18.42%
}
RISK_PROFILE = os.getenv("RISK_PROFILE", "OPTIMAL").upper()
if RISK_PROFILE not in RISK_PROFILES_MAP:
    RISK_PROFILE = "OPTIMAL"

TIER1_SIZE, MAX_CONVICTION_SIZE = RISK_PROFILES_MAP[RISK_PROFILE]

# --- СТРУКТУРА ДАНИХ QUANTCORE V7.8 (40 ФАКТОРІВ) ---
CANDLES_FETCH_LIMIT = 2600
EXCHANGE_LEVERAGE = 2

FEATURE_COLS = [
    'vol_96', 'vol_ratio_96_384',
    'tsmom_48', 'tsmom_96', 'tsmom_192', 'tsmom_384', 'tsmom_768', 'tsmom_1536',
    'dist_ema48', 'dist_ema96', 'dist_ema192', 'dist_ema384', 'dist_ema768', 'dist_ema1536',
    'spread_96_384', 'spread_192_768', 'spread_384_1536',
    'slope_384', 'slope_768', 'slope_1536',
    'ker_raw_96', 'signed_ker_96', 'ker_raw_192', 'signed_ker_192',
    'ker_raw_288', 'signed_ker_288', 'ker_raw_576', 'signed_ker_576',
    'donchian_96', 'donchian_384', 'donchian_768', 'donchian_1536',
    'rsi_14', 'rsi_64', 'rsi_192', 'zscore_96', 'vol_surge',
    'taker_imb_32', 'taker_imb_96', 'taker_imb_192'
]

# --- ПОРОГИ ГІСТЕРЕЗИСУ ТА ЗАХИСТУ V7.8 ULTRA ---
ENTER_LONG_TH = 0.35
EXIT_LONG_TH = -0.05
ENTER_SHORT_TH = 99.0
EXIT_SHORT_TH = 0.15
MIN_HOLD_BARS = 48
MIN_KER_ENTRY = 0.05
DIP_ADD_ACTIVE = True

# --- ВИКОНАВЧІ ЛІМІТИ ТА ЗАХИСТ ---
MIN_TRADE_BTC = 0.002
ACTION_DEADZONE = 0.25
CASH_ZONE_THRESHOLD = 0.08
MAX_DAILY_LOSS_PCT = 0.06
MAX_ALLOWED_SPREAD_PCT = 0.0008

EMERGENCY_SL_ATR_MULT = 3.5
ATR_BREAKEVEN_TRIGGER = 1.8
BREAKEVEN_BUFFER_PCT = 0.0007

# --- МОДУЛЬ НОВИН GEMINI AI ---
ENABLE_NEWS_SENTIMENT = True
GEMINI_MODEL = "gemini-3.5-flash-lite"
NEWS_REQUEST_TIMEOUT = 12

# --- ФАНДІНГ ТА ТАЙМАУТИ ---
MAX_FUNDING_RATE = 0.0004
FUNDING_BUFFER_MINUTES = 15
MAKER_TIMEOUT_SEC = 20

# --- ДИНАМІЧНИЙ СТАН У ПАМ'ЯТІ ---
IS_PAUSED = False
PAUSE_UNTIL = None
TRADE_ENTRY_PRICE = 0.0
TRADE_CANDLES_COUNT = 0
IS_BREAKEVEN_TRIGGERED = False
IS_TP1_TRIGGERED = False
INITIAL_TRADE_AMOUNT = 0.0
ACTIVE_SL_PRICE = 0.0

# --- ЛОГУВАННЯ ---
logger = logging.getLogger("TradingBot")
logger.setLevel(logging.INFO)

if not logger.handlers:
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)