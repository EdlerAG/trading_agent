from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import HTMLResponse
from app.core.security import verify_password_raw, EXPECTED_SESSION_TOKEN
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
async def login_terminal(payload: AuthLoginRequest, response: Response):
    """Авторизація у веб-терміналі зі встановленням захищеного HttpOnly сесійного кукі."""
    if not verify_password_raw(payload.password):
        raise HTTPException(status_code=401, detail="Невірний пароль доступу")

    response.set_cookie(
        key="qc_session",
        value=EXPECTED_SESSION_TOKEN,
        max_age=30 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True, "token": EXPECTED_SESSION_TOKEN}