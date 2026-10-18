from fastapi import APIRouter, Depends, Request, HTTPException
from app.core.security import verify_api_access
from app.core.events import event_bus, EventType
from app.domain.schemas import (
    CoinControlUpdateRequest,
    RiskProfileUpdateRequest,
    PauseControlRequest,
)

router = APIRouter(prefix="/api/v1/control", tags=["Multi-Currency & Risk Control"])


@router.post("/coin")
async def update_coin_control(
    request: Request,
    payload: CoinControlUpdateRequest,
    _: str = Depends(verify_api_access),
):
    """
    Індивідуальне налаштування конкретної валюти на льоту:
    - enabled: True / False
    - mode: 0 (OFF), 1 (AUTO), 2 (LONG_ONLY), 3 (SHORT_ONLY), 4 (CORE_TREND_ONLY)
    - base_weight: пріоритет капіталу (0.10 .. 2.50)
    - max_long_lev / max_short_lev: індивідуальна стеля плеча монети
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    updated_coin = container.state_service.update_coin_settings(
        symbol=payload.symbol.upper(),
        enabled=payload.enabled,
        mode=payload.mode,
        base_weight=payload.base_weight,
        max_long_lev=payload.max_long_lev,
        max_short_lev=payload.max_short_lev,
    )
    await event_bus.publish(EventType.COIN_CONFIG_CHANGED, {"coin": updated_coin}, wake_engine=True)
    return {"ok": True, "coin": updated_coin}


@router.post("/risk")
async def update_portfolio_risk_profile(
    request: Request,
    payload: RiskProfileUpdateRequest,
    _: str = Depends(verify_api_access),
):
    """
    Змінює глобальний профіль ризику портфеля (CONSERVATIVE 1.6x, OPTIMAL 2.4x,
    AGGRESSIVE 3.2x, OVERDRIVE 3.5x) та режим оркестратора (PORTFOLIO_SYNERGY / SOLO_MAX).
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    res = container.state_service.set_risk_profile(
        profile_name=payload.risk_profile,
        orchestrator_mode=payload.orchestrator_mode,
    )
    await event_bus.publish(EventType.RISK_PROFILE_CHANGED, res, wake_engine=True)
    return {"ok": True, **res}


@router.post("/pause")
async def set_trading_pause(
    request: Request,
    payload: PauseControlRequest,
    _: str = Depends(verify_api_access),
):
    """Ставить торгівлю на паузу (на N годин або безстроково) чи відновлює роботу."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    res = container.state_service.set_pause_state(paused=payload.paused, hours=payload.hours)
    if not payload.paused:
        event_bus.trigger_wakeup()
    return {"ok": True, **res}


@router.post("/wakeup")
async def force_candle_recalculation(_: str = Depends(verify_api_access)):
    """Миттєво будить торговий оркестратор для позачергового перерахунку всіх валют."""
    await event_bus.publish(EventType.FORCE_RECALC, {}, wake_engine=True)
    return {"ok": True, "message": "Запит на миттєвий перерахунок свічки відправлено!"}


@router.post("/panic")
async def emergency_panic_close_all(request: Request, _: str = Depends(verify_api_access)):
    """Аварійна ліквідація позицій по всіх валютах у 100% кеш USDT та постановка на паузу."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    container.state_service.set_pause_state(paused=True, hours=None)
    report = await container.orchestrator.emergency_close_all_positions()
    return {"ok": True, "report": report}