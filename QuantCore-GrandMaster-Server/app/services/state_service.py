import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Iterable
import orjson

from app.core.config import settings, RISK_PROFILES_MAP, SYMBOL_SPECS
from app.domain.enums import CoinMode, CascadePhase, TierRole
from app.domain.interfaces import IService
from app.domain.schemas import CoinStateDTO


class StateService(IService):
    """
    Єдине джерело стану сервера в оперативній пам'яті з атомарною синхронізацією
    у файл storage/engine_state.json через швидкий Rust-серіалізатор orjson.
    """

    __slots__ = (
        "is_paused",
        "pause_until",
        "risk_profile",
        "max_portfolio_lev",
        "orchestrator_mode",
        "active_cartridge",
        "force_step",
        "daily_starting_equity",
        "last_reset_date",
        "coins",
        "latest_telemetry",
        "last_candle_ts",
        "updated_at",
    )

    def __init__(self) -> None:
        self.is_paused: bool = False
        self.pause_until: Optional[datetime] = None
        self.risk_profile: str = settings.DEFAULT_RISK_PROFILE
        if self.risk_profile not in RISK_PROFILES_MAP:
            self.risk_profile = "OPTIMAL"
        self.max_portfolio_lev: float = RISK_PROFILES_MAP[self.risk_profile][1]
        self.orchestrator_mode: str = settings.DEFAULT_ORCHESTRATOR_MODE
        self.active_cartridge: str = "auto"
        self.force_step: bool = False
        self.daily_starting_equity: float = 0.0
        self.last_reset_date: Optional[str] = None
        self.coins: Dict[str, CoinStateDTO] = {}
        self.latest_telemetry: Dict[str, Any] = {}
        self.last_candle_ts: str = ""
        self.updated_at: str = datetime.now(timezone.utc).isoformat()

        self._init_default_coins(settings.DEFAULT_SYMBOLS)

    @property
    def name(self) -> str:
        return "StateService"

    def _init_default_coins(self, symbols: Iterable[str]) -> None:
        for sym in symbols:
            clean = sym.upper()
            if clean not in self.coins:
                _, _, _, def_role, def_w = settings.get_symbol_spec(clean)
                max_l = 2.55 if def_role == 1 else 2.00
                self.coins[clean] = CoinStateDTO(
                    symbol=clean,
                    enabled=True,
                    mode=int(CoinMode.AUTO),
                    tier_role=def_role,
                    base_weight=def_w,
                    max_long_lev=max_l,
                    max_short_lev=1.25,
                )

    async def init(self) -> None:
        self.load_snapshot()

    async def shutdown(self) -> None:
        self.save_snapshot()

    def sync_supported_symbols(self, symbols: Iterable[str]) -> None:
        self._init_default_coins(symbols)
        self.save_snapshot()

    def load_snapshot(self) -> None:
        if not os.path.exists(settings.STATE_FILE):
            self.save_snapshot()
            return
        try:
            with open(settings.STATE_FILE, "rb") as f:
                data = orjson.loads(f.read())

            self.is_paused = bool(data.get("is_paused", False))
            pu_raw = data.get("pause_until")
            self.pause_until = datetime.fromisoformat(pu_raw) if pu_raw else None

            prof = str(data.get("risk_profile", self.risk_profile)).upper()
            if prof in RISK_PROFILES_MAP:
                self.risk_profile = prof
                self.max_portfolio_lev = float(data.get("max_portfolio_lev") or RISK_PROFILES_MAP[prof][1])

            self.orchestrator_mode = str(data.get("orchestrator_mode", self.orchestrator_mode)).upper()
            self.active_cartridge = str(data.get("active_cartridge", "auto"))
            self.force_step = bool(data.get("force_step", False))
            self.daily_starting_equity = float(data.get("daily_starting_equity", 0.0))
            self.last_reset_date = data.get("last_reset_date")
            self.latest_telemetry = data.get("telemetry", {})

            coins_raw = data.get("coins", {})
            for sym, c_dict in coins_raw.items():
                clean = sym.upper()
                _, _, _, def_role, def_w = settings.get_symbol_spec(clean)
                self.coins[clean] = CoinStateDTO(
                    symbol=clean,
                    enabled=bool(c_dict.get("enabled", True)),
                    mode=int(c_dict.get("mode", 1)),
                    tier_role=int(c_dict.get("tier_role", def_role)),
                    base_weight=float(c_dict.get("base_weight", def_w)),
                    max_long_lev=float(c_dict.get("max_long_lev", 2.40)),
                    max_short_lev=float(c_dict.get("max_short_lev", 1.25)),
                    current_pos_qty=float(c_dict.get("current_pos_qty", 0.0)),
                    entry_price=float(c_dict.get("entry_price", 0.0)),
                    active_sl_price=float(c_dict.get("active_sl_price", 0.0)),
                    is_breakeven=bool(c_dict.get("is_breakeven", False)),
                    bars_held=int(c_dict.get("bars_held", 0)),
                    phase=int(c_dict.get("phase", 0)),
                    last_signal=float(c_dict.get("last_signal", 0.0)),
                    alpha_score=float(c_dict.get("alpha_score", 0.0)),
                    mwu_trust=float(c_dict.get("mwu_trust", 1.05)),
                )
        except Exception:
            pass

    def save_snapshot(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        coins_serialized = {
            sym: {
                "enabled": c.enabled,
                "mode": c.mode,
                "tier_role": c.tier_role,
                "base_weight": round(c.base_weight, 3),
                "max_long_lev": round(c.max_long_lev, 3),
                "max_short_lev": round(c.max_short_lev, 3),
                "current_pos_qty": c.current_pos_qty,
                "entry_price": round(c.entry_price, 4),
                "active_sl_price": round(c.active_sl_price, 4),
                "is_breakeven": c.is_breakeven,
                "bars_held": c.bars_held,
                "phase": c.phase,
                "last_signal": round(c.last_signal, 4),
                "alpha_score": round(c.alpha_score, 4),
                "mwu_trust": round(c.mwu_trust, 4),
            }
            for sym, c in self.coins.items()
        }

        payload = {
            "schema_version": "2.0",
            "is_paused": self.is_paused,
            "pause_until": self.pause_until.isoformat() if self.pause_until else None,
            "risk_profile": self.risk_profile,
            "max_portfolio_lev": self.max_portfolio_lev,
            "orchestrator_mode": self.orchestrator_mode,
            "active_cartridge": self.active_cartridge,
            "force_step": self.force_step,
            "daily_starting_equity": round(self.daily_starting_equity, 2),
            "last_reset_date": self.last_reset_date,
            "coins": coins_serialized,
            "telemetry": self.latest_telemetry,
            "updated_at": self.updated_at,
        }
        try:
            tmp_path = settings.STATE_FILE + ".tmp"
            with open(tmp_path, "wb") as f:
                f.write(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
            os.replace(tmp_path, settings.STATE_FILE)
        except Exception:
            pass

    def check_and_auto_resume_pause(self) -> bool:
        """Повертає True, якщо пауза щойно автоматично завершилася за таймером."""
        if self.is_paused and self.pause_until is not None:
            if datetime.now(timezone.utc) >= self.pause_until:
                self.is_paused = False
                self.pause_until = None
                self.save_snapshot()
                return True
        return False

    def set_pause_state(self, paused: bool, hours: Optional[float] = None) -> Dict[str, Any]:
        self.is_paused = bool(paused)
        if self.is_paused and hours and hours > 0:
            self.pause_until = datetime.now(timezone.utc) + timedelta(hours=float(hours))
        else:
            self.pause_until = None
        self.save_snapshot()
        return {
            "is_paused": self.is_paused,
            "pause_until": self.pause_until.isoformat() if self.pause_until else None,
        }

    def set_risk_profile(self, profile_name: str, orchestrator_mode: Optional[str] = None) -> Dict[str, Any]:
        prof = profile_name.strip().upper()
        if prof in RISK_PROFILES_MAP:
            self.risk_profile = prof
            self.max_portfolio_lev = RISK_PROFILES_MAP[prof][1]
        if orchestrator_mode and orchestrator_mode.strip().upper() in ("PORTFOLIO_SYNERGY", "SOLO_MAX"):
            self.orchestrator_mode = orchestrator_mode.strip().upper()
        self.force_step = True
        self.save_snapshot()
        return {
            "risk_profile": self.risk_profile,
            "max_portfolio_lev": self.max_portfolio_lev,
            "orchestrator_mode": self.orchestrator_mode,
        }

    def update_coin_settings(
        self,
        symbol: str,
        enabled: Optional[bool] = None,
        mode: Optional[int] = None,
        base_weight: Optional[float] = None,
        max_long_lev: Optional[float] = None,
        max_short_lev: Optional[float] = None,
    ) -> Dict[str, Any]:
        clean = symbol.strip().upper()
        if clean not in self.coins:
            self._init_default_coins([clean])

        c = self.coins[clean]
        if enabled is not None:
            c.enabled = bool(enabled)
        if mode is not None and 0 <= int(mode) <= 4:
            c.mode = int(mode)
            if c.mode == 0:
                c.enabled = False
            elif enabled is None:
                c.enabled = True
        if base_weight is not None:
            c.base_weight = max(0.10, min(2.50, float(base_weight)))
        if max_long_lev is not None:
            c.max_long_lev = max(0.20, min(3.50, float(max_long_lev)))
        if max_short_lev is not None:
            c.max_short_lev = max(0.00, min(2.50, float(max_short_lev)))

        self.force_step = True
        self.save_snapshot()
        return self._coin_to_dict(c)

    @staticmethod
    def _coin_to_dict(c: CoinStateDTO) -> Dict[str, Any]:
        mode_enum = CoinMode(c.mode) if c.mode in (0, 1, 2, 3, 4) else CoinMode.AUTO
        phase_enum = CascadePhase(c.phase) if c.phase in (-1, 0, 1, 2, 3) else CascadePhase.SCANNING_CASH
        role_enum = TierRole(c.tier_role) if c.tier_role in (1, 2, 3) else TierRole.STRUCTURAL_MAJOR
        return {
            "symbol": c.symbol,
            "enabled": c.enabled and (c.mode != 0),
            "mode": c.mode,
            "mode_label": mode_enum.label_ua,
            "tier_role": c.tier_role,
            "role_label": role_enum.label_ua,
            "base_weight": round(c.base_weight, 2),
            "mwu_trust": round(c.mwu_trust, 2),
            "effective_weight": round(c.base_weight * c.mwu_trust, 2),
            "max_long_lev": round(c.max_long_lev, 2),
            "max_short_lev": round(c.max_short_lev, 2),
            "current_pos_qty": c.current_pos_qty,
            "entry_price": round(c.entry_price, 4),
            "active_sl_price": round(c.active_sl_price, 4),
            "is_breakeven": c.is_breakeven,
            "bars_held": c.bars_held,
            "phase": c.phase,
            "phase_label": phase_enum.label_ua,
            "last_signal": round(c.last_signal, 4),
            "alpha_score": round(c.alpha_score, 4),
        }

    def get_coins_radar_list(self) -> List[Dict[str, Any]]:
        coin_prices = self.latest_telemetry.get("coin_prices", {})
        coin_upnl = self.latest_telemetry.get("coin_upnl", {})
        coin_targets = self.latest_telemetry.get("coin_targets", {})

        out = []
        for sym, c in self.coins.items():
            d = self._coin_to_dict(c)
            price = float(coin_prices.get(sym, 0.0))
            d["price"] = price
            d["notional_usdt"] = round(abs(c.current_pos_qty) * price, 2)
            d["unrealized_pnl"] = round(float(coin_upnl.get(sym, 0.0)), 2)
            d["target_weight"] = round(float(coin_targets.get(sym, 0.0)), 3)
            out.append(d)
        return out

    def get_full_state_dict(self) -> Dict[str, Any]:
        return {
            "is_paused": self.is_paused,
            "pause_until": self.pause_until.isoformat() if self.pause_until else None,
            "risk_profile": self.risk_profile,
            "max_portfolio_lev": self.max_portfolio_lev,
            "orchestrator_mode": self.orchestrator_mode,
            "daily_starting_equity": round(self.daily_starting_equity, 2),
            "last_candle_ts": self.last_candle_ts,
            "updated_at": self.updated_at,
            "telemetry": self.latest_telemetry,
            "coins": self.get_coins_radar_list(),
        }