from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy, closes


class MacdCross(Strategy):
    """Buy when the MACD line crosses above its signal line, sell on the opposite cross."""

    name = "macd_cross"
    default_params = {"fast": 12, "slow": 26, "signal": 9, "require_below_zero": False}

    @property
    def min_candles(self) -> int:
        return self.params["slow"] + self.params["signal"] + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        line, sig, _ = ind.macd(
            closes(candles), self.params["fast"], self.params["slow"], self.params["signal"]
        )
        if not in_position and ind.crossed_above(line, sig):
            if self.params["require_below_zero"] and line[-1] >= 0:
                return Signal.HOLD
            return Signal.BUY
        if in_position and ind.crossed_below(line, sig):
            return Signal.SELL
        return Signal.HOLD
