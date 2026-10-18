from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from app.core.security import verify_api_access
from app.domain.schemas import CartridgeSelectRequest

router = APIRouter(prefix="/api/v1/cartridge", tags=["AI Cartridge Hot-Swap"])

MAX_CARTRIDGE_UPLOAD_BYTES = 65 * 1024 * 1024  # Макс. 65 МБ на .joblib бандл


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
    file: UploadFile = File(...),
    _: str = Depends(verify_api_access),
):
    """
    Завантажує новий .joblib файл моделі (наприклад, з Google Colab)
    і виконує гарячу заміну (Hot-Swap) на льоту без перезапуску сервера.
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=503, detail="Сервіси ще ініціалізуються")

    raw_bytes = await file.read(MAX_CARTRIDGE_UPLOAD_BYTES + 1)
    if len(raw_bytes) > MAX_CARTRIDGE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл картриджа перевищує ліміт 65 МБ")

    try:
        info = await container.cartridge_service.hot_swap_from_bytes(
            filename=file.filename or "quant_core_uploaded.joblib",
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
    _: str = Depends(verify_api_access),
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
async def rollback_cartridge(request: Request, _: str = Depends(verify_api_access)):
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