import pytest

from binancebot import indicators as ind


def test_sma():
    assert ind.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    out = ind.ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)  # 4*0.5 + 2*0.5
    assert out[4] == pytest.approx(4.0)


def test_rsi_extremes():
    up = [float(i) for i in range(30)]
    assert ind.rsi(up, 14)[-1] == 100.0
    down = [float(30 - i) for i in range(30)]
    assert ind.rsi(down, 14)[-1] == pytest.approx(0.0)


def test_stddev_matches_naive():
    vals = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    out = ind.stddev(vals, 4)
    for i in range(3, len(vals)):
        w = vals[i - 3 : i + 1]
        m = sum(w) / 4
        assert out[i] == pytest.approx((sum((x - m) ** 2 for x in w) / 4) ** 0.5)


def test_bollinger_band_order():
    vals = [float(10 + (i % 5)) for i in range(40)]
    lower, mid, upper = ind.bollinger(vals, 20, 2)
    assert lower[-1] < mid[-1] < upper[-1]


def test_crosses():
    a = [1.0, 3.0]
    b = [2.0, 2.0]
    assert ind.crossed_above(a, b)
    assert not ind.crossed_below(a, b)
    assert ind.crossed_below(b, a)
    assert not ind.crossed_above([None, 3.0], b)


def test_atr_and_supertrend_lengths():
    highs = [float(i + 2) for i in range(50)]
    lows = [float(i) for i in range(50)]
    closes = [float(i + 1) for i in range(50)]
    a = ind.atr(highs, lows, closes, 10)
    assert a[8] is None and a[9] is not None
    line, direction = ind.supertrend(highs, lows, closes, 10, 3)
    assert len(line) == len(direction) == 50
    assert direction[-1] == 1  # steady up-trend
