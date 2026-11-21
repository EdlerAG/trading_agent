import logging
from typing import Dict, Any, List
from app.domain.enums import CoinMode
from app.domain.interfaces import IService
from app.domain.schemas import PortfolioTargetDTO
from app.services.state_service import StateService


class CurrencyGovernorService(IService):
    """
    Губернатор Валют (Currency Matrix & Allocation Governor):
    - Застосовує користувацькі обмеження режимів (AUTO, LONG_ONLY, SHORT_ONLY, CORE_ONLY, OFF)
      та індивідуальні стелі плеча до виходу будь-якого ШІ-картриджа.
    - Формує зведену матрицю розподілу маржі для Веб-термінала та Telegram.
    """

    __slots__ = ("_logger", "_state")

    def __init__(self, logger: logging.Logger, state_service: StateService) -> None:
        self._logger = logger
        self._state = state_service

    @property
    def name(self) -> str:
        return "CurrencyGovernorService"

    async def init(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def enforce_currency_rules(self, portfolio: PortfolioTargetDTO) -> PortfolioTargetDTO:
        """
        Перевіряє та коригує цільові ваги кожної монети відповідно до актуального
        стану пульта валют у StateService.
        """
        gross = 0.0
        net = 0.0

        for sym, target in portfolio.targets.items():
            c_state = self._state.coins.get(sym)
            if c_state is None:
                continue

            if not c_state.enabled or c_state.mode == int(CoinMode.OFF):
                target.desired_weight = 0.0
                target.phase = 0
            elif c_state.mode == int(CoinMode.LONG_ONLY) and target.desired_weight < 0.0:
                target.desired_weight = 0.0
                target.phase = 0
            elif c_state.mode == int(CoinMode.SHORT_ONLY) and target.desired_weight > 0.0:
                target.desired_weight = 0.0
                target.phase = 0

            if target.desired_weight > c_state.max_long_lev:
                target.desired_weight = c_state.max_long_lev
            elif target.desired_weight < -c_state.max_short_lev:
                target.desired_weight = -c_state.max_short_lev

            target.desired_weight = round(float(target.desired_weight), 4)
            gross += abs(target.desired_weight)
            net += target.desired_weight

        max_cap = float(self._state.max_portfolio_lev)
        if gross > max_cap and gross > 1e-6:
            scale = max_cap / gross
            gross = 0.0
            net = 0.0
            for target in portfolio.targets.values():
                target.desired_weight = round(target.desired_weight * scale, 4)
                gross += abs(target.desired_weight)
                net += target.desired_weight

        portfolio.total_gross_leverage = round(gross, 3)
        portfolio.net_leverage = round(net, 3)
        return portfolio

    def get_governor_summary(self) -> List[Dict[str, Any]]:
        return self._state.get_coins_radar_list()