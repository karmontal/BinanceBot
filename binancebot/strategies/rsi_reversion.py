from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy, closes


class RsiReversion(Strategy):
    """Buy when RSI climbs back out of oversold, sell when it reaches the exit level."""

    name = "rsi_reversion"
    default_params = {"period": 14, "oversold": 30, "overbought": 70}

    @property
    def min_candles(self) -> int:
        return self.params["period"] + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        r = ind.rsi(closes(candles), self.params["period"])
        if r[-1] is None or r[-2] is None:
            return Signal.HOLD
        if not in_position and r[-2] < self.params["oversold"] <= r[-1]:
            return Signal.BUY
        if in_position and r[-1] >= self.params["overbought"]:
            return Signal.SELL
        return Signal.HOLD
