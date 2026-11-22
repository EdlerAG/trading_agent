import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.domain.interfaces import IExchangeGateway, IService
from app.domain.schemas import PortfolioTargetDTO
from app.services.database_service import DatabaseService
from app.services.state_service import StateService


class RiskGuardService(IService):
    """
    Незалежний CRO Ризик-Менеджер та Watchdog (RiskGuardService — V6.1 Hard Safety Rails):
      1. Daily Drawdown Breaker (> 5%): закриває всі позиції в кеш і ставить паузу на 6 годин.
      2. Total Peak-to-Trough Drawdown Hard Stop (> 20%): закриває всі позиції і блокує торги до ручної перевірки.
      3. Hard Gross Leverage Cap (<= 2.25x): пропорційно стискає будь-який портфель понад ліміт валового плеча.
      4. Stale Market Data Guard: блокує генерацію ордерів при застарілих свічках BTC або кошика.
    """

    __slots__ = ("_logger", "_state", "_db", "_exchange", "_orchestrator")

    def __init__(
        self,
        logger: logging.Logger,
        state_service: StateService,
        db_service: DatabaseService,
        exchange_service: IExchangeGateway,
    ) -> None:
        self._logger = logger
        self._state = state_service
        self._db = db_service
        self._exchange = exchange_service
        self._orchestrator = None

    @property
    def name(self) -> str:
        return "RiskGuardService"

    def bind_orchestrator(self, orchestrator) -> None:
        self._orchestrator = orchestrator

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def check_stale_market_data(
        self,
        candles_map: Dict[str, Any],
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Повертає (is_stale, reason). Блокує торги, якщо свічка BTC або >30% кошика застаріли."""
        if not candles_map or "BTCUSDT" not in candles_map:
            return True, "missing_btcusdt_candles"

        now_sec = float(now_ts if now_ts is not None else time.time())
        candle_dur_sec = float(settings.CANDLE_INTERVAL_MINUTES) * 60.0
        max_age_sec = candle_dur_sec * float(settings.MAX_CANDLE_STALENESS_MULT)

        btc_df = candles_map["BTCUSDT"]
        if btc_df is None or len(btc_df) == 0:
            return True, "empty_btcusdt_candles"

        if "open_ms" in btc_df.columns:
            # Вік останньої ЗАКРИТОЇ свічки рахується від моменту її закриття (open_ms + candle_dur_sec)!
            btc_close_sec = (float(btc_df["open_ms"].iloc[-1]) / 1000.0) + candle_dur_sec
            btc_age = max(0.0, now_sec - btc_close_sec)
            if btc_age > max_age_sec:
                return True, f"stale_btcusdt_{btc_age / 60.0:.1f}m"

            stale_cnt = 0
            checked_cnt = 0
            for _sym, df in candles_map.items():
                if df is None or len(df) == 0 or "open_ms" not in df.columns:
                    continue
                checked_cnt += 1
                sym_close_sec = (float(df["open_ms"].iloc[-1]) / 1000.0) + candle_dur_sec
                sym_age = max(0.0, now_sec - sym_close_sec)
                if sym_age > max_age_sec * 1.25:
                    stale_cnt += 1
            if checked_cnt >= 5 and stale_cnt > checked_cnt * 0.30:
                return True, f"stale_universe_{stale_cnt}_of_{checked_cnt}"

        return False, ""

    def enforce_gross_leverage_cap(
        self,
        portfolio: PortfolioTargetDTO,
        max_gross: Optional[float] = None,
    ) -> PortfolioTargetDTO:
        """Жорсткий серверний обмежувач валового плеча (<= MAX_GROSS_LEVERAGE_CAP = 2.25x)."""
        hard_cap = float(settings.MAX_GROSS_LEVERAGE_CAP)
        eff_cap = min(float(max_gross), hard_cap) if (max_gross is not None and max_gross > 0.0) else hard_cap

        gross = sum(abs(float(t.desired_weight)) for t in portfolio.targets.values())
        if gross > eff_cap + 1e-9 and gross > 0.0:
            scale = eff_cap / gross
            self._logger.warning(
                f"🛡️ [RiskGuard] Валове плече {gross:.3f}x > ліміту {eff_cap:.2f}x -> стиснуто в {scale:.4f}x."
            )
            new_gross = 0.0
            new_net = 0.0
            for t in portfolio.targets.values():
                t.desired_weight = float(t.desired_weight) * scale
                t.raw_model_pos = float(t.raw_model_pos) * scale
                new_gross += abs(t.desired_weight)
                new_net += t.desired_weight
            portfolio.total_gross_leverage = new_gross
            portfolio.net_leverage = abs(new_net)
        return portfolio

    async def check_circuit_breaker(self, total_equity: float) -> Tuple[bool, str]:
        """Повертає (tripped, reason) для денного (>5%) та загального (>15% від піку) стоп-кранів."""
        if total_equity <= 0.0:
            return False, ""

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        changed_state = False

        if self._state.peak_equity <= 0.0 or total_equity > self._state.peak_equity:
            self._state.peak_equity = float(total_equity)
            changed_state = True

        if self._state.last_reset_date != today_str or self._state.daily_starting_equity <= 0.0:
            past_pnl = self._db.get_daily_realized_pnl()
            base_eq = total_equity - past_pnl if (total_equity - past_pnl) > 0 else total_equity
            self._state.daily_starting_equity = float(base_eq)
            self._state.last_reset_date = today_str
            changed_state = True

        if changed_state:
            self._state.save_snapshot()

        # 1. Загальна просадка від історичного піку (> 15% -> ПОВНА ЗУПИНКА до ручного аудиту!)
        peak_eq = float(self._state.peak_equity)
        if peak_eq > 0.0:
            total_dd = (peak_eq - total_equity) / peak_eq
            if total_dd > float(settings.MAX_TOTAL_DRAWDOWN_PCT) and not self._state.is_paused:
                self._state.set_pause_state(paused=True, hours=None)
                if self._orchestrator is not None:
                    await self._orchestrator.emergency_close_all_positions()
                reason = (
                    f"🛑 <b>HARD TOTAL DRAWDOWN STOP (> {settings.MAX_TOTAL_DRAWDOWN_PCT:.0%})!</b>\n"
                    f"• Пік: <code>${peak_eq:,.2f}</code> -> Поточний: <code>${total_equity:,.2f}</code> "
                    f"(<b>-{total_dd:.2%}</b>)\n"
                    f"• Усі позиції ліквідовано в кеш. Авто-відновлення ВИМКНЕНО до ручної ревізії (/resume)."
                )
                self._logger.critical(reason)
                return True, reason

        # 2. Денна просадка (> 5% -> закриття позицій і 6-годинний захисний кулдаун)
        start_eq = float(self._state.daily_starting_equity)
        if start_eq > 0.0:
            daily_dd = (start_eq - total_equity) / start_eq
            if daily_dd > float(settings.MAX_DAILY_LOSS_PCT) and not self._state.is_paused:
                self._state.set_pause_state(paused=True, hours=6.0)
                if self._orchestrator is not None:
                    await self._orchestrator.emergency_close_all_positions()
                reason = (
                    f"🛑 <b>DAILY CIRCUIT BREAKER (> {settings.MAX_DAILY_LOSS_PCT:.0%})!</b>\n"
                    f"• Просадка доби: <b>-{daily_dd:.2%}</b> (від <code>${start_eq:,.2f}</code>)\n"
                    f"• Позиції закрито в кеш. Пауза 6 годин."
                )
                self._logger.error(reason)
                return True, reason

        return False, ""

    async def loop(self) -> None:
        while True:
            try:
                # Zero-Idle CPU: якщо торгівля не на тимчасовій паузі — спимо 900с без пробуджень
                if self._state.is_paused and self._state.pause_until is not None:
                    rem = (self._state.pause_until - datetime.now(timezone.utc)).total_seconds()
                    sleep_s = max(5.0, min(60.0, rem + 1.0))
                else:
                    sleep_s = 900.0
                await asyncio.sleep(sleep_s)
                if self._state.check_and_auto_resume_pause():
                    self._logger.info("🟢 [RiskWatchdog] Таймер паузи вичерпано — торгівлю автоматично відновлено.")
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(300.0)
