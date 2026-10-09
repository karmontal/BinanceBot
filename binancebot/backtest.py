"""Replay historical candles through the exact same TradingBot logic."""
from __future__ import annotations

import csv
import os
from typing import Any, Dict, List, Optional

from .bot import BotConfig, TradingBot, lookback_for
from .broker import PaperBroker
from .metrics import compute_metrics
from .models import Candle
from .strategies import create_strategy

__all__ = ["lookback_for", "run_backtest", "save_candles_csv", "load_candles_csv"]


def run_backtest(
    cfg: BotConfig,
    candles: List[Candle],
    fee_rate: float = 0.001,
    slippage_pct: float = 0.05,
    start_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Replay ``candles``. Candles opening before ``start_ms`` are only used as
    indicator warm-up: no trading and no equity recorded for them."""
    strategy = create_strategy(cfg.strategy, cfg.params)
    broker = PaperBroker(cfg.starting_balance, fee_rate=fee_rate, slippage_pct=slippage_pct)
    bot = TradingBot(cfg, strategy, broker)
    lookback = bot.lookback
    for i, c in enumerate(candles):
        if start_ms is not None and c.open_time < start_ms:
            continue
        bot.check_risk(c.low, c.high, c.close_time, open_price=c.open)
        bot.on_closed_candles(candles[max(0, i + 1 - lookback) : i + 1], price=c.close)
    metrics = compute_metrics(bot.equity_curve, bot.trades, cfg.starting_balance, cfg.interval)
    return {"name": cfg.name, "strategy": cfg.strategy, "metrics": metrics, "trades": bot.trades, "equity": bot.equity_curve}


def save_candles_csv(path: str, candles: List[Candle]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
        for c in candles:
            w.writerow([c.open_time, c.open, c.high, c.low, c.close, c.volume, c.close_time])


def load_candles_csv(path: str) -> List[Candle]:
    with open(path, newline="") as fh:
        r = csv.DictReader(fh)
        return [
            Candle(
                int(row["open_time"]), float(row["open"]), float(row["high"]), float(row["low"]),
                float(row["close"]), float(row["volume"]), int(row["close_time"]),
            )
            for row in r
        ]
