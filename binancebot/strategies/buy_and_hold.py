from __future__ import annotations

from typing import List

from ..models import Candle, Signal
from .base import Strategy


class BuyAndHold(Strategy):
    """Benchmark: buy once and never sell."""

    name = "buy_and_hold"
    default_params = {}

    @property
    def min_candles(self) -> int:
        return 1

    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        return Signal.HOLD if in_position else Signal.BUY
