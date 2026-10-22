import os
import re
import shutil
import logging
from typing import Optional, Dict, Any, List
import joblib

from app.core.config import settings
from app.core.memory_guard import memory_guard
from app.core.events import event_bus, EventType
from app.domain.interfaces import IService, IAlphaCartridge
from app.cartridges.v58_grand_master_cartridge import V58GrandMasterCartridge


class CartridgeLoaderService(IService):
    """
    Сервіс керування картриджами ШІ-моделей (.joblib) покоління QuantCore V58.0 Pure SOTA:
    - Автоматично знаходить та завантажує найновіший мультивалютний бандл при старті.
    - Якщо файлу .joblib на диску ще немає — запускає автономне ядро V58 Pure SOTA.
    - Підтримує гарячу заміну (Hot-Swap) моделі з Telegram або Web-інтерфейсу за 1.5 сек без рестарту.
    """

    __slots__ = ("_logger", "_active_cartridge", "_active_filename", "_previous_filename")

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._active_cartridge: Optional[IAlphaCartridge] = None
        self._active_filename: str = "v58_autonomous_sota"
        self._previous_filename: str = ""

    @property
    def name(self) -> str:
        return "CartridgeLoader"

    @property
    def active_name(self) -> str:
        return self._active_filename

    @property
    def cartridge(self) -> IAlphaCartridge:
        if self._active_cartridge is None:
            self._active_cartridge = V58GrandMasterCartridge(
                filename="v58_autonomous_sota",
                bundle={"symbols": list(settings.DEFAULT_SYMBOLS), "assets": {}},
            )
        return self._active_cartridge

    async def init(self) -> None:
        os.makedirs(settings.CARTRIDGES_DIR, exist_ok=True)
        for fname in os.listdir(settings.BASE_DIR):
            if fname.endswith(".joblib"):
                src = os.path.join(settings.BASE_DIR, fname)
                dst = os.path.join(settings.CARTRIDGES_DIR, fname)
                if os.path.isfile(src):
                    shutil.move(src, dst)

        candidates = self.list_available_cartridges()
        if not candidates:
            self._logger.info("ℹ️ Зовнішніх .joblib у storage/cartridges/ поки немає. Активовано автономне SOTA ядро V58.0.")
            self._active_cartridge = V58GrandMasterCartridge(
                filename="v58_autonomous_sota",
                bundle={"symbols": list(settings.DEFAULT_SYMBOLS), "assets": {}},
            )
            return

        preferred = candidates[0]
        for cand in candidates:
            c_low = cand.lower()
            if any(k in c_low for k in ("v58", "v53", "v52", "v51", "pure_sota", "sota", "quantum")):
                preferred = cand
                break

        self.load_cartridge_by_name(preferred)

    async def shutdown(self) -> None:
        self._active_cartridge = None
        memory_guard.trim_ram()

    def list_available_cartridges(self) -> List[str]:
        if not os.path.exists(settings.CARTRIDGES_DIR):
            return []
        files = []
        for f in os.listdir(settings.CARTRIDGES_DIR):
            if f.endswith(".joblib"):
                full_p = os.path.join(settings.CARTRIDGES_DIR, f)
                if os.path.isfile(full_p):
                    files.append((os.path.getmtime(full_p), f))
        files.sort(key=lambda x: x[0], reverse=True)
        return [f[1] for f in files]

    @staticmethod
    def _instantiate_adapter(filename: str, raw_bundle: Any) -> IAlphaCartridge:
        if isinstance(raw_bundle, IAlphaCartridge):
            return raw_bundle
        if not isinstance(raw_bundle, dict):
            raise ValueError(f"Файл '{filename}' не є коректним словником картриджа QuantCore.")

        return V58GrandMasterCartridge(filename=filename, bundle=raw_bundle)

    def load_cartridge_by_name(self, filename: str) -> Dict[str, Any]:
        safe_name = os.path.basename(filename)
        full_path = os.path.join(settings.CARTRIDGES_DIR, safe_name)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Картридж '{safe_name}' не знайдено у storage/cartridges/")

        self._logger.info(f"📦 Завантаження ШІ-картриджа '{safe_name}'...")
        raw_bundle = joblib.load(full_path)
        new_cartridge = self._instantiate_adapter(safe_name, raw_bundle)

        if (
            self._active_filename
            and self._active_filename != "v58_autonomous_sota"
            and self._active_filename != safe_name
        ):
            self._previous_filename = self._active_filename

        self._active_cartridge = new_cartridge
        self._active_filename = safe_name
        del raw_bundle

        freed_bytes = memory_guard.enforce_disk_quota(active_cartridge_filename=safe_name)
        rss_mb = memory_guard.trim_ram()

        symbols_list = list(new_cartridge.supported_symbols)
        meta = {
            "ok": True,
            "filename": safe_name,
            "active_cartridge": safe_name,
            "architecture": new_cartridge.architecture_name,
            "symbols": symbols_list,
            "supported_symbols": symbols_list,
            "ram_after_mb": rss_mb,
            "freed_bytes": freed_bytes,
        }
        self._logger.info(
            f"✅ Картридж '{safe_name}' ({new_cartridge.architecture_name}) активовано! "
            f"Валюти: {', '.join(new_cartridge.supported_symbols)} | RAM: {rss_mb:.1f} MB"
        )
        return meta

    def get_metadata(self) -> Dict[str, Any]:
        cart = self.cartridge
        symbols_list = list(cart.supported_symbols)
        return {
            "ok": True,
            "active_cartridge": self._active_filename,
            "architecture": cart.architecture_name,
            "supported_symbols": symbols_list,
            "symbols": symbols_list,
            "available_cartridges": self.list_available_cartridges(),
            "previous_cartridge": self._previous_filename,
        }

    async def hot_swap_from_bytes(self, filename: str, content: bytes) -> Dict[str, Any]:
        safe_name = os.path.basename(filename)
        if not safe_name.endswith(".joblib"):
            safe_name += ".joblib"
        target_path = os.path.join(settings.CARTRIDGES_DIR, safe_name)
        with open(target_path, "wb") as f:
            f.write(content)
        info = self.load_cartridge_by_name(safe_name)
        info["ok"] = True
        info["active_cartridge"] = safe_name
        info["supported_symbols"] = info.get("symbols", [])
        return info

    async def rollback_to_previous(self) -> Dict[str, Any]:
        if not self._previous_filename:
            raise RuntimeError("Немає попереднього картриджа для відкату.")
        self._logger.warning(f"🔄 Відкат до попереднього картриджа '{self._previous_filename}'...")
        res = self.load_cartridge_by_name(self._previous_filename)
        self._previous_filename = ""
        res["ok"] = True
        res["active_cartridge"] = self._active_filename
        res["supported_symbols"] = res.get("symbols", [])
        return res
