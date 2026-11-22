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
        "v2_live_state.json",
        "v3_live_state.json",
        "shadow_arena_state.json",
        "adaptive_weights.json",
        "online_learning.json",
        "trading_history.db",
        "trading_history.db-wal",
        "trading_history.db-shm",
        "trading_bot.log",
        "heartbeat.json",
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
        """Читає фактичний фізичний обсяг зайнятої RAM (Linux /proc або Windows PSAPI)."""
        try:
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return round(int(line.split()[1]) / 1024.0, 2)
        except Exception:
            pass
        if os.name == "nt":
            try:
                from ctypes import wintypes

                class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                pmc = _PROCESS_MEMORY_COUNTERS()
                pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
                k32 = ctypes.windll.kernel32
                k32.GetCurrentProcess.restype = wintypes.HANDLE
                handle = k32.GetCurrentProcess()
                fn = getattr(k32, "K32GetProcessMemoryInfo", None) or ctypes.windll.psapi.GetProcessMemoryInfo
                fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
                fn.restype = wintypes.BOOL
                if fn(handle, ctypes.byref(pmc), pmc.cb):
                    return round(float(pmc.WorkingSetSize) / (1024.0 * 1024.0), 2)
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

        removed_bytes += self.prune_market_cache(max_mb=getattr(settings, "MAX_MARKET_CACHE_MB", 200))

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
    def prune_market_cache(max_mb: int = 200, max_age_days: int = 14) -> int:
        """Обмежує директорію storage/market_cache/ стелею <= max_mb МБ та видаляє застарілі .tmp/кеш-файли."""
        cache_dir = getattr(settings, "MARKET_CACHE_DIR", "")
        if not cache_dir or not os.path.exists(cache_dir):
            return 0
        max_bytes = max(10, int(max_mb)) * 1024 * 1024
        now_s = time.time()
        max_age_sec = max(1, int(max_age_days)) * 86400.0
        freed = 0
        entries: List[Tuple[float, int, str, str]] = []
        total_b = 0

        for root, _, fnames in os.walk(cache_dir):
            for fn in fnames:
                fp = os.path.join(root, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                if fn.endswith(".tmp") and (now_s - st.st_mtime) > 600:
                    try:
                        os.remove(fp)
                        freed += st.st_size
                    except OSError:
                        pass
                    continue
                if fn != "v3_aux_cache.pkl" and (now_s - st.st_mtime) > max_age_sec:
                    try:
                        os.remove(fp)
                        freed += st.st_size
                    except OSError:
                        pass
                    continue
                total_b += st.st_size
                entries.append((st.st_mtime, st.st_size, fn, fp))

        if total_b > max_bytes:
            # Сортуємо від найстаріших; активний v3_aux_cache.pkl ставимо останнім у чергу видалення
            entries.sort(key=lambda x: (1 if x[2] == "v3_aux_cache.pkl" else 0, x[0]))
            target_b = int(max_bytes * 0.85)
            for _mt, fsz, _fn, fp in entries:
                try:
                    os.remove(fp)
                    total_b -= fsz
                    freed += fsz
                    if total_b <= target_b:
                        break
                except OSError:
                    pass
        return freed

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