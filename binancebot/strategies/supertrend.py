from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy


class Supertrend(Strategy):
    """Follow the ATR-based Supertrend: long while it is green, flat while it is red."""

    name = "supertrend"
    default_params = {"period": 10, "multiplier": 3.0}

    @property
    def min_candles(self) -> int:
        return self.params["period"] + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        _, direction = ind.supertrend(
            [c.high for c in candles],
            [c.low for c in candles],
            [c.close for c in candles],
            self.params["period"],
            self.params["multiplier"],
        )
        if direction[-1] is None or direction[-2] is None:
            return Signal.HOLD
        if not in_position and direction[-2] == -1 and direction[-1] == 1:
            return Signal.BUY
        if in_position and direction[-1] == -1:
            return Signal.SELL
        return Signal.HOLD
