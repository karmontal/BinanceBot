import threading
import time

import pytest

from binancebot import runner
from binancebot.config import Settings, load_config
from binancebot.storage import Storage
from binancebot.synthetic import generate_candles


class FakeMarketClient:
    """Serves synthetic candles, revealing one more each call."""

    def __init__(self, *a, **kw):
        self.candles = generate_candles(800, "1h", seed=3)
        self.cursor = 400
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

    def closed_klines(self, symbol, interval, limit):
        with self.lock:
            self.cursor = min(self.cursor + 1, len(self.candles))
            return self.candles[max(0, self.cursor - limit) : self.cursor]

    def price(self, symbol):
        with self.lock:
            return self.candles[self.cursor - 1].close


def test_config_loads_and_merges_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "mode: paper\ndefaults: {symbol: ETHUSDT, starting_balance: 500}\n"
        "bots:\n  - {name: a, strategy: sma_crossover, params: {fast: 5, slow: 10}}\n"
        "  - {name: b, strategy: supertrend, symbol: BTCUSDT}\n"
    )
    settings, bots = load_config(str(p))
    assert settings.mode == "paper"
    assert bots[0].symbol == "ETHUSDT" and bots[0].starting_balance == 500
    assert bots[1].symbol == "BTCUSDT"


def test_config_rejects_bad_bot(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("bots:\n  - {name: a, strategy: sma_crossover, params: {bogus: 1}}\n")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_repo_config_is_valid():
    settings, bots = load_config("config.yaml")
    assert settings.mode == "paper"
    assert len(bots) >= 8


def test_parallel_paper_bots(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "BinanceClient", FakeMarketClient)
    settings = Settings(poll_seconds=0.01, summary_minutes=999, db_path=str(tmp_path / "db.sqlite"))
    _, bots = load_config("config.yaml")
    bots = [b for b in bots if b.enabled]
    storage = Storage(settings.db_path)

    # Stop the runner by making the main-loop sleep raise KeyboardInterrupt after ~2s.
    real_sleep = time.sleep
    deadline = time.time() + 2.0

    def fake_sleep(s):
        if threading.current_thread() is threading.main_thread() and time.time() > deadline:
            raise KeyboardInterrupt
        real_sleep(min(s, 0.05))

    monkeypatch.setattr(runner.time, "sleep", fake_sleep)
    runner.run(settings, bots, storage)

    for cfg in bots:
        state = storage.load_state(cfg.name)
        assert state is not None, cfg.name
        assert storage.equity_curve(cfg.name), cfg.name
    assert storage.trades("buy_and_hold")[0]["side"] == "BUY"
    beats = storage.heartbeats()
    assert set(beats) == {b.name for b in bots}
    assert all(hb["price"] and hb["error"] is None for hb in beats.values())

    # Restart: state is restored, mismatched strategy is refused.
    rebuilt = runner.build_bots(settings, bots, storage)
    assert len(rebuilt) == len(bots)
    bots[1].strategy = "macd_cross"
    with pytest.raises(SystemExit):
        runner.build_bots(settings, bots, storage)


def test_live_mode_is_locked(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.delenv("BINANCE_LIVE_CONFIRM", raising=False)
    with pytest.raises(SystemExit):
        runner._trading_client("live")
