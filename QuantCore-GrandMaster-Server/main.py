import os

# Жорстке обмеження багатопотоковості C-бібліотек для мінімального споживання RAM на 1GB VPS
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["MALLOC_TRIM_THRESHOLD_"] = "65536"
os.environ["MALLOC_ARENA_MAX"] = "2"

import gc
import time
import ctypes
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, HTMLResponse
from dotenv import load_dotenv

# --- БАЗОВІ ШЛЯХИ ТА СХОВИЩЕ STORAGE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
CARTRIDGES_DIR = os.path.join(STORAGE_DIR, "cartridges")
BACKUPS_DIR = os.path.join(STORAGE_DIR, "backups")

for _folder in (STORAGE_DIR, CARTRIDGES_DIR, BACKUPS_DIR):
    os.makedirs(_folder, exist_ok=True)

load_dotenv(os.path.join(BASE_DIR, ".env"))

# --- НАЛАШТУВАННЯ ЛОГУВАННЯ ---
LOG_PATH = os.path.join(STORAGE_DIR, "trading_bot.log")
logger = logging.getLogger("QuantCoreServer")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _fh = RotatingFileHandler(LOG_PATH, maxBytes=4 * 1024 * 1024, backupCount=2, encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)

    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)


# --- АПАРАТНИЙ КОНТРОЛЬ ОПЕРАТИВНОЇ ПАМ'ЯТІ (1GB RAM VPS SHIELD) ---
def trim_process_memory() -> float:
    """
    Виконує збір сміття Python (gc.collect) та примусово повертає вільні сторінки кучі
    назад ядру Linux через glibc malloc_trim(0). Повертає поточний RSS у МБ.
    """
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024.0, 2)
    except Exception:
        pass
    return 0.0


# --- ГЛОБАЛЬНІ ПОДІЇ СИНХРОНІЗАЦІЇ ---
WAKEUP_EVENT = asyncio.Event()
SHUTDOWN_EVENT = asyncio.Event()


async def _wait_until_next_15m_candle(interval_minutes: int = 15) -> bool:
    """
    Zero-Idle CPU Hibernation:
    Процес спить із 0.00% навантаженням на CPU рівно до закриття 15m свічки (+3.5 сек)
    або миттєво прокидається при отриманні сигналу WAKEUP_EVENT з Telegram / Web UI.
    """
    rss_mb = trim_process_memory()
    now = time.time()
    candle_sec = interval_minutes * 60
    next_boundary = (int(now // candle_sec) + 1) * candle_sec + 4
    sleep_seconds = max(1.0, next_boundary - now)

    next_str = datetime.fromtimestamp(next_boundary, tz=timezone.utc).strftime("%H:%M:%S UTC")
    logger.info(f"💤 Гібернація (0% CPU | RAM: {rss_mb:.1f} MB) на {sleep_seconds:.0f}с до {next_str}...")

    try:
        await asyncio.wait_for(WAKEUP_EVENT.wait(), timeout=sleep_seconds)
        WAKEUP_EVENT.clear()
        logger.info("⚡ Миттєве пробудження ядра за командою користувача!")
        return True
    except asyncio.TimeoutError:
        return False


async def trading_engine_loop(orchestrator):
    """Головний фоновий цикл торгового оркестратора (15m свічки + реал-тайм самонавчання)."""
    logger.info("⚙️ Торговий цикл QuantCore активовано (Режим: Zero-Idle CPU Hibernation).")

    # Стартовий розрахунок одразу після запуску
    try:
        await orchestrator.run_step(force_recalc=True)
    except Exception as e:
        logger.error(f"Помилка стартового кроку оркестратора: {e}", exc_info=True)

    while not SHUTDOWN_EVENT.is_set():
        forced = await _wait_until_next_15m_candle(interval_minutes=15)
        if SHUTDOWN_EVENT.is_set():
            break
        try:
            await orchestrator.run_step(force_recalc=forced)
        except Exception as e:
            logger.error(f"Помилка ітерації свічки: {e}", exc_info=True)
            if hasattr(orchestrator, "notify_error"):
                await orchestrator.notify_error(str(e))
        finally:
            trim_process_memory()


# --- LIFESPAN-ОРКЕСТРАТОР FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Ініціалізація QuantCore Sovereign Server...")
    tasks = []
    orchestrator = None

    try:
        # Динамічне підключення модулів із пакета app/
        from app.services.service_registry import build_application_container
        container = await build_application_container(
            base_dir=BASE_DIR,
            storage_dir=STORAGE_DIR,
            wakeup_event=WAKEUP_EVENT,
            logger=logger
        )
        app.state.container = container
        orchestrator = container.orchestrator

        tasks.append(asyncio.create_task(trading_engine_loop(orchestrator), name="trading_loop"))
        if container.telegram_bot is not None:
            tasks.append(asyncio.create_task(container.telegram_bot.polling_loop(), name="tg_polling"))
        if container.watchdog is not None:
            tasks.append(asyncio.create_task(container.watchdog.loop(), name="risk_watchdog"))

        rss_now = trim_process_memory()
        logger.info(f"✅ Усі мікросервіси запущено! Поточне споживання RAM: {rss_now:.1f} MB.")
    except ImportError as imp_err:
        logger.warning(
            f"⚠️ Модулі пакета app/ ще не всі створено ({imp_err}). "
            f"Сервер працює у режимі готовності інфраструктури."
        )
        app.state.container = None
    except Exception as init_err:
        logger.critical(f"❌ Помилка під час ініціалізації контейнера сервісів: {init_err}", exc_info=True)
        app.state.container = None

    yield

    # Graceful Shutdown: коректна зупинка всіх фонових задач та атомарне збереження стану
    logger.info("🛑 Отримано сигнал зупинки. Збереження стану engine_state.json та online_learning.json...")
    SHUTDOWN_EVENT.set()
    WAKEUP_EVENT.set()

    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    if getattr(app.state, "container", None) is not None:
        try:
            await app.state.container.shutdown()
        except Exception as e:
            logger.error(f"Помилка при закритті контейнера: {e}")

    logger.info("✅ Сервер безпечно зупинено.")


# --- ІНІЦІАЛІЗАЦІЯ FASTAPI ЗАСТОСУНКУ ---
app = FastAPI(
    title="QuantCore Sovereign Multi-Asset Terminal",
    version="23.0-GrandMaster",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# Підключення маршрутів API та легкого Web-терміналу (якщо файли app/api вже створені)
try:
    from app.api.router import api_router
    app.include_router(api_router)
except ImportError:
    pass


@app.get("/health", tags=["System"])
async def health_check():
    """Ендпоінт моніторингу здоров'я та споживання оперативної пам'яті (1GB VPS)."""
    rss_mb = trim_process_memory()
    container = getattr(app.state, "container", None)
    cartridge_name = "none"
    is_paused = False

    if container is not None:
        cartridge_name = getattr(container.cartridge_Service, "active_name", "loaded")
        is_paused = getattr(container.state_service, "is_paused", False)

    return {
        "status": "ok",
        "ram_rss_mb": rss_mb,
        "ram_limit_mb": 420,
        "active_cartridge": cartridge_name,
        "is_paused": is_paused,
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }


@app.post("/api/v1/system/wakeup", tags=["System"])
async def trigger_immediate_wakeup():
    """Миттєво будить торговий цикл для позачергового перерахунку свічки."""
    WAKEUP_EVENT.set()
    return {"ok": True, "message": "Сигнал негайного перерахунку відправлено!"}


if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8501"))
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        loop="auto",
        http="auto",
        access_log=False,
        limit_concurrency=32,
        timeout_keep_alive=15,
    )