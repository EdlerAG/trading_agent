from fastapi import APIRouter, Depends, Request, Response, HTTPException
from fastapi.responses import HTMLResponse
from app.core.config import settings
from app.core.security import (
    authenticate_login_password,
    verify_api_access,
    check_login_rate_limit,
    record_login_failure,
    reset_login_failures,
)
from app.domain.schemas import AuthLoginRequest
from app.api.endpoints_telemetry import router as telemetry_router
from app.api.endpoints_control import router as control_router
from app.api.endpoints_cartridge import router as cartridge_router

api_router = APIRouter()
api_router.include_router(telemetry_router)
api_router.include_router(control_router)
api_router.include_router(cartridge_router)


@api_router.get("/", response_class=HTMLResponse, tags=["Web Terminal"])
async def serve_web_terminal():
    """Віддає надлегкий Glassmorphism Bento-UI термінал напряму з пам'яті (0 МБ оверхеду)."""
    try:
        from app.web.portal_html import PORTAL_HTML
        return HTMLResponse(content=PORTAL_HTML, status_code=200)
    except ImportError:
        return HTMLResponse(
            content="<h3>QuantCore Sovereign Server Online. Web UI module (app/web/portal_html.py) pending.</h3>",
            status_code=200,
        )


@api_router.post("/api/v1/auth/login", tags=["Auth"])
async def login_terminal(payload: AuthLoginRequest, request: Request, response: Response):
    """Авторизація у веб-терміналі (admin або viewer) зі встановленням HttpOnly кукі."""
    client_ip = request.client.host if request.client else "unknown"
    check_login_rate_limit(client_ip)
    auth_res = authenticate_login_password(payload.password)
    if auth_res is None:
        record_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="Невірний пароль доступу")

    role, session_token = auth_res
    reset_login_failures(client_ip)
    response.set_cookie(
        key="qc_session",
        value=session_token,
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return {"ok": True, "role": role}


@api_router.post("/api/v1/auth/logout", tags=["Auth"])
async def logout_terminal(response: Response):
    """Скидає HttpOnly сесію веб-термінала для перемикання ролі."""
    response.delete_cookie(key="qc_session")
    return {"ok": True}


@api_router.get("/api/v1/auth/session", tags=["Auth"])
async def get_session_role(role: str = Depends(verify_api_access)):
    """Повертає поточну роль автентифікованого клієнта (admin або viewer)."""
    return {"ok": True, "role": role}