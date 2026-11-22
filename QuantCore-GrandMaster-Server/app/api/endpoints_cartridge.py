import re
from typing import Tuple
from fastapi import APIRouter, Depends, Request, HTTPException
from app.core.config import settings
from app.core.security import verify_api_access, verify_admin_access
from app.domain.schemas import CartridgeSelectRequest

router = APIRouter(prefix="/api/v1/cartridge", tags=["AI Cartridge Hot-Swap"])

MAX_CARTRIDGE_UPLOAD_BYTES = 65 * 1024 * 1024  # Макс. 65 МБ на .joblib бандл


def _extract_multipart_or_raw(body: bytes, content_type: str, fallback_name: str) -> Tuple[str, bytes]:
    """Легкий парсер multipart/form-data без обов'язкової залежності від python-multipart."""
    if "multipart/form-data" not in content_type.lower():
        return fallback_name, body
    m_bnd = re.search(r"boundary=([^;\s]+)", content_type, flags=re.IGNORECASE)
    if not m_bnd:
        return fallback_name, body
    boundary = m_bnd.group(1).strip('"').encode("latin-1")
    parts = body.split(b"--" + boundary)
    for part in parts:
        if b"Content-Disposition" not in part:
            continue
        sep_idx = part.find(b"\r\n\r\n")
        if sep_idx < 0:
            continue
        hdr_bytes = part[:sep_idx]
        payload = part[sep_idx + 4 :]
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        hdr_str = hdr_bytes.decode("utf-8", errors="replace")
        fn_match = re.search(r'filename="([^"]+)"', hdr_str)
        fname = fn_match.group(1) if fn_match else fallback_name
        return fname, payload
    return fallback_name, body


@router.get("/list")
async def list_cartridges_and_online_weights(request: Request, _: str = Depends(verify_api_access)):
    """Повертає метадані активного картриджа, список .joblib на диску та стан онлайн-самонавчання."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    return {
        "ok": True,
        "cartridge": container.cartridge_service.get_metadata(),
        "online_learning": container.online_learner.get_summary_dict(),
    }


@router.post("/upload")
async def upload_and_hotswap_cartridge(
    request: Request,
    _: str = Depends(verify_admin_access),
):
    """
    Завантажує новий .joblib файл моделі (multipart/form-data або raw body)
    і виконує гарячу заміну (Hot-Swap) на льоту без перезапуску сервера.
    Працює навіть без встановленого python-multipart!
    """
    if not settings.ALLOW_CARTRIDGE_UPLOAD:
        raise HTTPException(status_code=403, detail="Завантаження картриджів вимкнено конфігурацією безпеки")

    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    body = await request.body()
    if len(body) > MAX_CARTRIDGE_UPLOAD_BYTES + 65536:
        raise HTTPException(status_code=413, detail="Файл картриджа перевищує ліміт 65 МБ")

    ctype = request.headers.get("content-type", "")
    default_fn = request.headers.get("x-filename", "quant_core_uploaded.joblib")
    fname, raw_bytes = _extract_multipart_or_raw(body, ctype, default_fn)

    if len(raw_bytes) > MAX_CARTRIDGE_UPLOAD_BYTES or len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Порожній або занадто великий файл картриджа")

    try:
        info = await container.cartridge_service.hot_swap_from_bytes(
            filename=fname or "quant_core_uploaded.joblib",
            content=raw_bytes,
        )
        container.state_service.sync_supported_symbols(info["supported_symbols"])
        return info
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.post("/activate")
async def activate_existing_cartridge(
    request: Request,
    payload: CartridgeSelectRequest,
    _: str = Depends(verify_admin_access),
):
    """Перемикає активну модель між збереженими файлами .joblib у storage/cartridges/."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    try:
        info = container.cartridge_service.load_cartridge_by_name(payload.filename)
        container.state_service.sync_supported_symbols(info["supported_symbols"])
        return info
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rollback")
async def rollback_cartridge(request: Request, _: str = Depends(verify_admin_access)):
    """Миттєвий відкат на попередню робочу модель .joblib."""
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    try:
        info = await container.cartridge_service.rollback_to_previous()
        container.state_service.sync_supported_symbols(info["supported_symbols"])
        return info
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
