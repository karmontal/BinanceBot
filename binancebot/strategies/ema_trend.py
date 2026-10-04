from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy, closes


class EmaTrend(Strategy):
    """EMA crossover that only buys while price is above a long-term trend EMA."""

    name = "ema_trend"
    default_params = {"fast": 12, "slow": 26, "trend": 200}

    @property
    def min_candles(self) -> int:
        return self.params["trend"] + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        c = closes(candles)
        fast = ind.ema(c, self.params["fast"])
        slow = ind.ema(c, self.params["slow"])
        trend = ind.ema(c, self.params["trend"])
        if trend[-1] is None:
            return Signal.HOLD
        if not in_position and c[-1] > trend[-1] and ind.crossed_above(fast, slow):
            return Signal.BUY
        if in_position and (ind.crossed_below(fast, slow) or c[-1] < trend[-1]):
            return Signal.SELL
        return Signal.HOLD
