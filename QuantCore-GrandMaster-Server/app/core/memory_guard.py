import gc
import os
import time
import ctypes
from typing import Dict, Any, List, Tuple
from app.core.config import settings


class MemoryAndDiskGuard:
    """
    Контролер ресурсів 1GB RAM VPS та обмеженого диска:
    1. Повертає фізичні сторінки RAM операційній системі Linux через glibc malloc_trim(0).
    2. Автоматично чистить застарілі бекапи та старі версії .joblib моделей (LRU Quota),
       гарантовано зберігаючи поточну активну модель, БД та файли стану.
    """

    __slots__ = ("_libc",)

    PROTECTED_FILENAMES = frozenset({
        "engine_state.json",
        "adaptive_weights.json",
        "online_learning.json",
        "trading_history.db",
        "trading_history.db-wal",
        "trading_history.db-shm",
        "trading_bot.log",
    })

    def __init__(self) -> None:
        self._libc = None
        try:
            self._libc = ctypes.CDLL("libc.so.6")
        except Exception:
            self._libc = None

    def trim_ram(self) -> float:
        """Примусове очищення Garbage Collector + повернення арени C-аллокатора в ядро Linux."""
        gc.collect()
        if self._libc is not None:
            try:
                self._libc.malloc_trim(0)
            except Exception:
                pass
        return self.get_rss_mb()

    @staticmethod
    def get_rss_mb() -> float:
        """Читає фактичний фізичний обсяг зайнятої RAM (VmRSS) з /proc/self/status."""
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024.0, 2)
        except Exception:
            pass
        return 0.0

    def enforce_disk_quota(self, active_cartridge_filename: str = "") -> int:
        removed_bytes = 0

        removed_bytes += self._prune_directory(
            directory=settings.CARTRIDGES_DIR,
            keep_count=settings.MAX_CARTRIDGES_KEPT,
            protected_name=active_cartridge_filename,
            extensions=(".joblib", ".pkl", ".bin"),
        )

        removed_bytes += self._prune_directory(
            directory=settings.BACKUPS_DIR,
            keep_count=settings.MAX_BACKUPS_KEPT,
            protected_name="",
            extensions=(".db", ".gz", ".zip", ".bak", ".json"),
        )

        all_files: List[Tuple[float, int, str]] = []
        total_bytes = 0

        for root, _, filenames in os.walk(settings.STORAGE_DIR):
            for fname in filenames:
                full_path = os.path.join(root, fname)
                try:
                    st = os.stat(full_path)
                    total_bytes += st.st_size
                    if fname in self.PROTECTED_FILENAMES or fname == active_cartridge_filename:
                        continue
                    all_files.append((st.st_mtime, st.st_size, full_path))
                except OSError:
                    pass

        if total_bytes > settings.MAX_STORAGE_BYTES:
            all_files.sort(key=lambda x: x[0])
            target_bytes = int(settings.MAX_STORAGE_BYTES * 0.82)
            for _, fsize, fpath in all_files:
                try:
                    os.remove(fpath)
                    total_bytes -= fsize
                    removed_bytes += fsize
                    if total_bytes <= target_bytes:
                        break
                except OSError:
                    pass

        return removed_bytes

    @staticmethod
    def _prune_directory(
        directory: str,
        keep_count: int,
        protected_name: str,
        extensions: Tuple[str, ...],
    ) -> int:
        if not os.path.exists(directory):
            return 0

        entries: List[Tuple[float, int, str, str]] = []
        for fname in os.listdir(directory):
            if fname.endswith(".tmp") or fname.endswith(extensions):
                fpath = os.path.join(directory, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    st = os.stat(fpath)
                    if fname.endswith(".tmp") and ((time.time() - st.st_mtime) > 600):
                        os.remove(fpath)
                        continue
                    entries.append((st.st_mtime, st.st_size, fname, fpath))
                except OSError:
                    pass

        if len(entries) <= keep_count:
            return 0

        entries.sort(key=lambda x: x[0], reverse=True)
        kept = 0
        freed = 0

        for _, fsize, fname, fpath in entries:
            if fname == protected_name:
                continue
            kept += 1
            if kept >= keep_count:
                try:
                    os.remove(fpath)
                    freed += fsize
                except OSError:
                    pass
        return freed

    def get_resource_telemetry(self, active_cartridge: str = "") -> Dict[str, Any]:
        total_storage_bytes = 0
        cartridges_list: List[str] = []

        for root, _, filenames in os.walk(settings.STORAGE_DIR):
            for fname in filenames:
                fpath = os.path.join(root, fname)
                try:
                    total_storage_bytes += os.path.getsize(fpath)
                except OSError:
                    pass
                if root == settings.CARTRIDGES_DIR and fname.endswith(".joblib"):
                    cartridges_list.append(fname)

        return {
            "ram_rss_mb": self.get_rss_mb(),
            "storage_used_mb": round(total_storage_bytes / (1024.0 * 1024.0), 2),
            "storage_limit_mb": settings.MAX_STORAGE_MB,
            "available_cartridges": sorted(cartridges_list),
            "active_cartridge": active_cartridge,
        }


memory_guard = MemoryAndDiskGuard()