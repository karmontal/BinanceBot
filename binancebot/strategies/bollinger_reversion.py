from __future__ import annotations

from typing import List

from .. import indicators as ind
from ..models import Candle, Signal
from .base import Strategy, closes


class BollingerReversion(Strategy):
    """Buy when price closes back inside the lower band, sell at the middle/upper band."""

    name = "bollinger_reversion"
    default_params = {"period": 20, "num_std": 2.0, "exit": "middle"}  # exit: middle | upper

    def __init__(self, **params):
        super().__init__(**params)
        if self.params["exit"] not in ("middle", "upper"):
            raise ValueError("bollinger_reversion: exit must be 'middle' or 'upper'")

    @property
    def min_candles(self) -> int:
        return self.params["period"] + 2

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        c = closes(candles)
        lower, mid, upper = ind.bollinger(c, self.params["period"], self.params["num_std"])
        if lower[-1] is None or lower[-2] is None:
            return Signal.HOLD
        if not in_position and c[-2] < lower[-2] and c[-1] >= lower[-1]:
            return Signal.BUY
        target = mid[-1] if self.params["exit"] == "middle" else upper[-1]
        if in_position and c[-1] >= target:
            return Signal.SELL
        return Signal.HOLD
