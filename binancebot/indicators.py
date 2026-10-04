"""Pure-python technical indicators.

Every function returns a list aligned with its input; positions without
enough data are ``None``.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

Series = List[Optional[float]]


def sma(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    if period <= 0:
        raise ValueError("period must be > 0")
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values: Sequence[Optional[float]], period: int) -> Series:
    """EMA seeded with the SMA of the first ``period`` non-None values."""
    out: Series = [None] * len(values)
    k = 2.0 / (period + 1)
    seed: List[float] = []
    prev: Optional[float] = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == period:
                prev = sum(seed) / period
                out[i] = prev
            continue
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """Wilder's RSI."""
    out: Series = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def stddev(values: Sequence[float], period: int) -> Series:
    """Rolling population standard deviation."""
    out: Series = [None] * len(values)
    total = total_sq = 0.0
    for i, v in enumerate(values):
        total += v
        total_sq += v * v
        if i >= period:
            old = values[i - period]
            total -= old
            total_sq -= old * old
        if i >= period - 1:
            mean = total / period
            out[i] = max(total_sq / period - mean * mean, 0.0) ** 0.5
    return out


def bollinger(values: Sequence[float], period: int = 20, num_std: float = 2.0):
    """Returns (lower, middle, upper)."""
    mid = sma(values, period)
    sd = stddev(values, period)
    lower: Series = [None] * len(values)
    upper: Series = [None] * len(values)
    for i, (m, s) in enumerate(zip(mid, sd)):
        if m is not None and s is not None:
            lower[i] = m - num_std * s
            upper[i] = m + num_std * s
    return lower, mid, upper


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    fast_e = ema(values, fast)
    slow_e = ema(values, slow)
    line: Series = [
        (f - s) if f is not None and s is not None else None for f, s in zip(fast_e, slow_e)
    ]
    sig = ema(line, signal)
    hist: Series = [
        (m - s) if m is not None and s is not None else None for m, s in zip(line, sig)
    ]
    return line, sig, hist


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[float]:
    tr = []
    for i in range(len(closes)):
        if i == 0:
            tr.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            tr.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return tr


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> Series:
    """Wilder's ATR."""
    tr = true_range(highs, lows, closes)
    out: Series = [None] * len(tr)
    if len(tr) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def highest(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = max(values[i - period + 1 : i + 1])
    return out


def lowest(values: Sequence[float], period: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = min(values[i - period + 1 : i + 1])
    return out


def supertrend(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 10,
    multiplier: float = 3.0,
):
    """Returns (line, direction) where direction is 1 (up-trend) or -1 (down-trend)."""
    n = len(closes)
    a = atr(highs, lows, closes, period)
    line: Series = [None] * n
    direction: List[Optional[int]] = [None] * n
    final_upper = final_lower = None
    for i in range(n):
        if a[i] is None:
            continue
        hl2 = (highs[i] + lows[i]) / 2
        basic_upper = hl2 + multiplier * a[i]
        basic_lower = hl2 - multiplier * a[i]
        if final_upper is None:
            final_upper, final_lower = basic_upper, basic_lower
            direction[i] = 1 if closes[i] > final_upper else -1
        else:
            prev_close = closes[i - 1]
            final_upper = basic_upper if (basic_upper < final_upper or prev_close > final_upper) else final_upper
            final_lower = basic_lower if (basic_lower > final_lower or prev_close < final_lower) else final_lower
            prev_dir = direction[i - 1] or -1
            if prev_dir == -1 and closes[i] > final_upper:
                direction[i] = 1
            elif prev_dir == 1 and closes[i] < final_lower:
                direction[i] = -1
            else:
                direction[i] = prev_dir
        line[i] = final_lower if direction[i] == 1 else final_upper
    return line, direction


def crossed_above(a: Series, b: Series, i: int = -1) -> bool:
    """True when series ``a`` crosses above ``b`` at index ``i``."""
    j = i - 1
    if None in (a[i], b[i], a[j], b[j]):
        return False
    return a[j] <= b[j] and a[i] > b[i]


def crossed_below(a: Series, b: Series, i: int = -1) -> bool:
    j = i - 1
    if None in (a[i], b[i], a[j], b[j]):
        return False
    return a[j] >= b[j] and a[i] < b[i]
