from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy, closes


class SmaCrossover(Strategy):
    """Buy when the fast SMA crosses above the slow SMA, sell on the opposite cross."""

    name = "sma_crossover"
    default_params = {"fast": 20, "slow": 50}

    @property
    def min_candles(self) -> int:
        return self.params["slow"] + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        c = closes(candles)
        fast = ind.sma(c, self.params["fast"])
        slow = ind.sma(c, self.params["slow"])
        if not in_position and ind.crossed_above(fast, slow):
            return Signal.BUY
        if in_position and ind.crossed_below(fast, slow):
            return Signal.SELL
        return Signal.HOLD
