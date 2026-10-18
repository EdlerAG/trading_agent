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
from app.cartridges.v23_grand_master_cartridge import V23GrandMasterCartridge


class CartridgeLoaderService(IService):
    """
    Сервіс керування картриджами ШІ-моделей (.joblib) покоління V23+ Grand-Master:
    - Автоматично знаходить та завантажує найновіший мультивалютний бандл при старті.
    - Якщо файлу .joblib на диску ще немає — запускає автономне структурне ядро V23 на 5 валют.
    - Підтримує гарячу заміну (Hot-Swap) моделі з Telegram або Web-інтерфейсу за 1.5 сек без рестарту.
    """

    __slots__ = ("_logger", "_active_cartridge", "_active_filename", "_previous_filename")

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._active_cartridge: Optional[IAlphaCartridge] = None
        self._active_filename: str = "v23_autonomous_structural"
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
            self._active_cartridge = V23GrandMasterCartridge(
                filename="v23_autonomous_structural",
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
            self._logger.info("ℹ️ Зовнішніх .joblib у storage/cartridges/ поки немає. Активовано автономне 5-валютне ядро V23.")
            self._active_cartridge = V23GrandMasterCartridge(
                filename="v23_autonomous_structural",
                bundle={"symbols": list(settings.DEFAULT_SYMBOLS), "assets": {}},
            )
            return

        preferred = candidates[0]
        for cand in candidates:
            if "v23" in cand.lower() or "grand_master" in cand.lower():
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
        if not isinstance(raw_bundle, dict) or "assets" not in raw_bundle:
            raise ValueError(
                f"Файл '{filename}' не є мультивалютним картриджем QuantCore V23+ (відсутній ключ 'assets')."
            )
        return V23GrandMasterCartridge(filename=filename, bundle=raw_bundle)

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
            and self._active_filename != "v23_autonomous_structural"
            and self._active_filename != safe_name
        ):
            self._previous_filename = self._active_filename

        self._active_cartridge = new_cartridge
        self._active_filename = safe_name
        del raw_bundle

        freed_bytes = memory_guard.enforce_disk_quota(active_cartridge_filename=safe_name)
        rss_mb = memory_guard.trim_ram()

        info = {
            "ok": True,
            "active_cartridge": self._active_filename,
            "architecture": new_cartridge.architecture_name,
            "supported_symbols": list(new_cartridge.supported_symbols),
            "ram_rss_mb": rss_mb,
            "disk_freed_kb": round(freed_bytes / 1024.0, 1),
        }
        self._logger.info(
            f"✅ Картридж '{safe_name}' ({new_cartridge.architecture_name}) активовано! "
            f"Валюти: {', '.join(new_cartridge.supported_symbols)} | RAM: {rss_mb:.1f} MB"
        )
        return info

    async def hot_swap_from_bytes(self, filename: str, content: bytes) -> Dict[str, Any]:
        clean_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", os.path.basename(filename))
        if not clean_name.endswith(".joblib"):
            clean_name += ".joblib"

        tmp_path = os.path.join(settings.CARTRIDGES_DIR, clean_name + ".tmp")
        final_path = os.path.join(settings.CARTRIDGES_DIR, clean_name)

        with open(tmp_path, "wb") as f:
            f.write(content)

        try:
            test_bundle = joblib.load(tmp_path)
            _ = self._instantiate_adapter(clean_name, test_bundle)
            del test_bundle
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            memory_guard.trim_ram()
            raise ValueError(f"Файл пошкоджено або несумісний із V23+ IAlphaCartridge: {e}")

        os.replace(tmp_path, final_path)
        res = self.load_cartridge_by_name(clean_name)
        await event_bus.publish(EventType.CARTRIDGE_HOT_SWAPPED, res, wake_engine=True)
        return res

    async def rollback_to_previous(self) -> Dict[str, Any]:
        available = [f for f in self.list_available_cartridges() if f != self._active_filename]
        target = self._previous_filename if self._previous_filename in available else (available[0] if available else "")
        if not target:
            raise ValueError("Попередній картридж для відкату відсутній на диску.")

        res = self.load_cartridge_by_name(target)
        await event_bus.publish(EventType.CARTRIDGE_HOT_SWAPPED, res, wake_engine=True)
        return res

    def get_metadata(self) -> Dict[str, Any]:
        c = self.cartridge
        return {
            "active_cartridge": self._active_filename,
            "previous_cartridge": self._previous_filename,
            "architecture": c.architecture_name,
            "supported_symbols": list(c.supported_symbols),
            "available_on_disk": self.list_available_cartridges(),
        }