import pytest

from binancebot.backtest import run_backtest
from binancebot.bot import BotConfig
from binancebot.models import Candle, Signal
from binancebot.strategies import STRATEGIES, create_strategy
from binancebot.synthetic import generate_candles


def series(closes):
    return [Candle(i, c, c * 1.001, c * 0.999, c, 1.0, i + 1) for i, c in enumerate(closes)]


def test_unknown_param_rejected():
    with pytest.raises(ValueError):
        create_strategy("sma_crossover", {"fastt": 3})


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError):
        create_strategy("nope")


def test_sma_crossover_signals():
    s = create_strategy("sma_crossover", {"fast": 2, "slow": 4})
    down_then_up = [10, 9, 8, 7, 6, 5, 9]
    assert s.generate_signal(series(down_then_up), in_position=False) is Signal.BUY
    up_then_down = [5, 6, 7, 8, 9, 10, 6]
    assert s.generate_signal(series(up_then_down), in_position=True) is Signal.SELL
    assert s.generate_signal(series(up_then_down), in_position=False) is Signal.HOLD


def test_rsi_reversion_buys_on_recovery():
    s = create_strategy("rsi_reversion", {"period": 5, "oversold": 30, "overbought": 70})
    closes = [100 - i * 2 for i in range(15)] + [100]
    assert s.generate_signal(series(closes), in_position=False) is Signal.BUY


def test_donchian_breakout():
    s = create_strategy("donchian_breakout", {"entry_period": 5, "exit_period": 3})
    assert s.generate_signal(series([10] * 10 + [12]), in_position=False) is Signal.BUY
    assert s.generate_signal(series([10] * 10 + [8]), in_position=True) is Signal.SELL


def test_bollinger_reversion_buys_back_inside_band():
    s = create_strategy("bollinger_reversion", {"period": 10, "num_std": 2.0})
    closes = [100, 101] * 10 + [90, 99]
    assert s.generate_signal(series(closes), in_position=False) is Signal.BUY


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_every_strategy_backtests_and_trades(name):
    candles = generate_candles(1500, "1h", seed=7)
    cfg = BotConfig(name=name, strategy=name, interval="1h", starting_balance=1000)
    result = run_backtest(cfg, candles)
    m = result["metrics"]
    assert len(result["equity"]) == len(candles)
    assert m["final_equity"] > 0
    buys = sum(1 for t in result["trades"] if t["side"] == "BUY")
    assert buys >= 1
    # Long-only, one position at a time: sides must alternate starting with BUY.
    sides = [t["side"] for t in result["trades"]]
    assert all(a != b for a, b in zip(sides, sides[1:]))
    assert sides[0] == "BUY"


def test_backtest_warmup_candles_are_not_traded():
    candles = generate_candles(600, "1h", seed=5)
    start = candles[200].open_time
    cfg = BotConfig(name="bh", strategy="buy_and_hold", interval="1h", starting_balance=1000)
    result = run_backtest(cfg, candles, start_ms=start)
    assert len(result["equity"]) == 400
    assert result["trades"][0]["ts"] == candles[200].close_time
    # Warm-up lets indicator strategies trade from the first in-range candle.
    cfg = BotConfig(name="e", strategy="ema_trend", interval="1h")
    warm = run_backtest(cfg, candles, start_ms=start)
    assert len(warm["equity"]) == 400
