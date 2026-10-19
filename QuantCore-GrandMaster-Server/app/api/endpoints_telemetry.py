import os
from collections import deque
from fastapi import APIRouter, Depends, Request, Query
from app.core.security import verify_api_access
from app.core.config import settings
from app.core.memory_guard import memory_guard

router = APIRouter(prefix="/api/v1", tags=["Telemetry & Analytics"])


@router.get("/state")
async def get_terminal_state(request: Request, _: str = Depends(verify_api_access)):
    """Повний зріз стану сервера, балансу, всіх 5 монет, онлайн-самонавчання та пам'яті."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False, "error": "Container initializing"}

    st_data = container.state_service.get_full_state_dict()
    cart_meta = container.cartridge_service.get_metadata()
    online_meta = container.online_learner.get_summary_dict()
    res_meta = memory_guard.get_resource_telemetry(cart_meta["active_cartridge"])

    return {
        "ok": True,
        "engine": st_data,
        "cartridge": cart_meta,
        "online_learning": online_meta,
        "resources": res_meta,
    }


@router.get("/radar")
async def get_multi_asset_radar(request: Request, _: str = Depends(verify_api_access)):
    """Детальний по-валютний радар фаз каскаду (F0..F4), сигналів ШІ та ваг довіри MWU."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False, "coins": {}}

    return {
        "ok": True,
        "coins": container.state_service.get_coins_radar_list(),
        "telemetry": container.state_service.latest_telemetry,
    }


@router.get("/equity")
async def get_equity_curve(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    _: str = Depends(verify_api_access),
):
    """Векторні ряди кривої капіталу, просадки (Drawdown) та котирувань BTC для графіків."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False, "series": [], "kpis": {}}

    return container.db_service.get_equity_series_and_kpis(days=days)


@router.get("/trades")
async def get_trades_journal(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    symbol: str = Query(default=""),
    _: str = Depends(verify_api_access),
):
    """Журнал виконаних ордерів з фільтрацією по конкретній монеті (BTCUSDT, ETHUSDT тощо)."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False, "trades": []}

    return {
        "ok": True,
        "trades": container.db_service.get_recent_trades(limit=limit, symbol=symbol),
    }


@router.get("/logs")
async def get_recent_logs(
    lines: int = Query(default=30, ge=5, le=120),
    _: str = Depends(verify_api_access),
):
    """Повертає останні рядки системного логу trading_bot.log без завантаження всього файлу в RAM."""
    if not os.path.exists(settings.LOG_PATH):
        return {"ok": True, "lines": []}
    try:
        with open(settings.LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            tail = [ln.rstrip("\r\n") for ln in deque(f, maxlen=lines)]
        return {"ok": True, "lines": tail}
    except Exception as e:
        return {"ok": False, "error": str(e), "lines": []}