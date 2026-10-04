from __future__ import annotations

from typing import Any, Dict, Type

from .base import Strategy
from .bollinger_reversion import BollingerReversion
from .buy_and_hold import BuyAndHold
from .donchian_breakout import DonchianBreakout
from .ema_trend import EmaTrend
from .macd_cross import MacdCross
from .rsi_reversion import RsiReversion
from .sma_crossover import SmaCrossover
from .supertrend import Supertrend

STRATEGIES: Dict[str, Type[Strategy]] = {
    cls.name: cls
    for cls in (
        BuyAndHold,
        SmaCrossover,
        EmaTrend,
        RsiReversion,
        BollingerReversion,
        MacdCross,
        DonchianBreakout,
        Supertrend,
    )
}


def create_strategy(name: str, params: Dict[str, Any] | None = None) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Unknown strategy {name!r}. Available: {sorted(STRATEGIES)}") from None
    return cls(**(params or {}))


__all__ = ["Strategy", "STRATEGIES", "create_strategy"]
