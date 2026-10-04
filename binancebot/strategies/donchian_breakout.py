from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy


class DonchianBreakout(Strategy):
    """Turtle-style breakout: buy above the N-candle high, sell below the M-candle low."""

    name = "donchian_breakout"
    default_params = {"entry_period": 20, "exit_period": 10}

    @property
    def min_candles(self) -> int:
        return max(self.params["entry_period"], self.params["exit_period"]) + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        # Channels are computed on the candles *before* the current one.
        prev = candles[:-1]
        last = candles[-1]
        upper = ind.highest([c.high for c in prev], self.params["entry_period"])[-1]
        lower = ind.lowest([c.low for c in prev], self.params["exit_period"])[-1]
        if upper is None or lower is None:
            return Signal.HOLD
        if not in_position and last.close > upper:
            return Signal.BUY
        if in_position and last.close < lower:
            return Signal.SELL
        return Signal.HOLD
