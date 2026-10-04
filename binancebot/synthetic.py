"""Synthetic OHLCV generator for offline demos and tests."""
from __future__ import annotations

import random
from typing import List

from .models import Candle, interval_ms


def generate_candles(n: int = 2000, interval: str = "1h", start_price: float = 30_000.0, seed: int = 42) -> List[Candle]:
    """Random walk with alternating bull / bear / sideways regimes."""
    rng = random.Random(seed)
    step = interval_ms(interval)
    t = 1_700_000_000_000
    price = start_price
    candles: List[Candle] = []
    drift = 0.0
    regime_left = 0
    for _ in range(n):
        if regime_left <= 0:
            drift = rng.choice([0.0015, -0.0012, 0.0, 0.0])
            regime_left = rng.randint(80, 300)
        regime_left -= 1
        vol = 0.008
        open_ = price
        close = open_ * (1 + drift + rng.gauss(0, vol))
        high = max(open_, close) * (1 + abs(rng.gauss(0, vol / 2)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, vol / 2)))
        candles.append(Candle(t, open_, high, low, close, rng.uniform(10, 100), t + step - 1))
        price = close
        t += step
    return candles
