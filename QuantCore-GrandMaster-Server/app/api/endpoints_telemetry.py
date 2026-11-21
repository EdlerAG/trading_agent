import os
from collections import deque
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse
from app.core.security import verify_api_access
from app.core.config import settings
from app.core.memory_guard import memory_guard

router = APIRouter(prefix="/api/v1", tags=["Telemetry & Analytics"])


@router.get("/state")
async def get_terminal_state(request: Request, _: str = Depends(verify_api_access)):
    """Повний зріз стану сервера, всіх активів, V2 телеметрії, новин та ресурсів."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False, "error": "Container initializing"}

    st_data = container.state_service.get_full_state_dict()
    cart_meta = container.cartridge_service.get_metadata()
    online_meta = container.online_learner.get_summary_dict()
    res_meta = memory_guard.get_resource_telemetry(cart_meta["active_cartridge"])
    news_meta = container.news_service.get_cached_info() if getattr(container, "news_service", None) else {}
    arena_meta = container.shadow_arena.get_leaderboard() if getattr(container, "shadow_arena", None) else []
    v2_meta = (
        container.db_service.get_v2_analytics_summary(days=30)
        if hasattr(container.db_service, "get_v2_analytics_summary")
        else {}
    )

    return {
        "ok": True,
        "demo_trading": settings.USE_DEMO_TRADING,
        "virtual_equity_cap": settings.VIRTUAL_EQUITY_CAP if settings.USE_DEMO_TRADING else 0.0,
        "cartridge_engine": settings.CARTRIDGE_ENGINE,
        "candle_timeframe": settings.CANDLE_TIMEFRAME,
        "engine": st_data,
        "cartridge": cart_meta,
        "online_learning": online_meta,
        "news": news_meta,
        "shadow_arena": arena_meta,
        "v2_analytics": v2_meta,
        "resources": res_meta,
    }


@router.get("/radar")
async def get_multi_asset_radar(request: Request, _: str = Depends(verify_api_access)):
    """Детальний по-валютний радар сигналів, рукавів (A/B) та факторів."""
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
    """Журнал виконаних ордерів з фільтрацією по конкретній монеті."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False, "trades": []}

    return {
        "ok": True,
        "trades": container.db_service.get_recent_trades(limit=limit, symbol=symbol),
    }


@router.get("/v2/telemetry")
async def get_v2_testnet_telemetry(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=25, ge=1, le=200),
    _: str = Depends(verify_api_access),
):
    """Зведена аналітика виконання V2 Testnet (maker %, сліпедж, фандінг, останні ордери)."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        return {"ok": False}

    summary = container.db_service.get_v2_analytics_summary(days=days)
    executions = container.db_service.get_v2_recent_executions(limit=limit)
    return {"ok": True, "summary": summary, "executions": executions}


@router.get("/v2/export")
async def download_v2_research_bundle(
    request: Request,
    _: str = Depends(verify_api_access),
):
    """Експортує SQLite + JSONL аудит-логи Testnet у ZIP для quant_v2/testnet_reconcile.py."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Container initializing")

    zip_path = container.db_service.export_v2_research_zip()
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=500, detail="Не вдалося сформувати ZIP-архів телеметрії")
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=os.path.basename(zip_path),
    )


@router.get("/news")
async def get_news_intelligence(
    request: Request,
    refresh: bool = Query(default=False),
    _: str = Depends(verify_api_access),
):
    """Останні заголовки RSS/Atom, макро-сентимент та статус захисту R5 Geo-Shock."""
    container = getattr(request.app.state, "container", None)
    if container is None or getattr(container, "news_service", None) is None:
        return {"ok": False, "news": {}}
    if refresh:
        await container.news_service.fetch_market_intelligence(force_refresh=True)
    return {"ok": True, "news": container.news_service.get_cached_info()}


@router.get("/arena")
async def get_shadow_arena_leaderboard(request: Request, _: str = Depends(verify_api_access)):
    """Турнірна таблиця Shadow Arena (6 паралельних віртуальних моделей на живих свічках)."""
    container = getattr(request.app.state, "container", None)
    if container is None or getattr(container, "shadow_arena", None) is None:
        return {"ok": False, "leaderboard": []}
    return {"ok": True, "leaderboard": container.shadow_arena.get_leaderboard()}


@router.get("/system/preflight")
async def get_system_preflight_check(request: Request, _: str = Depends(verify_api_access)):
    """Перевірка повної передстартової готовності сервера, ключів, One-Way Mode, BNB/BFUSD та RAM."""
    container = getattr(request.app.state, "container", None)
    if container is None or getattr(container, "exchange_service", None) is None:
        return {"ok": False}
    diag = await container.exchange_service.run_preflight_diagnostics()
    return {"ok": True, "preflight": diag}


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
