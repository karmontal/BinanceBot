"""A single trading bot: one strategy, one symbol, one budget."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .broker import Broker
from .models import Candle, Fill, Signal
from .storage import Storage
from .strategies import Strategy

log = logging.getLogger(__name__)


@dataclass
class BotConfig:
    name: str
    strategy: str
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    params: Dict[str, Any] = field(default_factory=dict)
    starting_balance: float = 1000.0
    position_size_pct: float = 100.0
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    mode: str = "paper"
    enabled: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.position_size_pct <= 100:
            raise ValueError(f"{self.name}: position_size_pct must be in (0, 100]")
        if self.mode not in ("paper", "testnet", "live"):
            raise ValueError(f"{self.name}: mode must be paper, testnet or live")


class TradingBot:
    """Turns strategy signals into orders and applies risk management.

    The same object drives both live/paper trading (``runner``) and
    backtests (``backtest``), so both share exactly the same logic.
    """

    def __init__(
        self,
        config: BotConfig,
        strategy: Strategy,
        broker: Broker,
        storage: Optional[Storage] = None,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.broker = broker
        self.storage = storage
        self.entry_price: Optional[float] = None
        self.entry_cost: float = 0.0  # quote spent on the open position (incl. fee)
        self.peak_price: Optional[float] = None
        self.last_candle_time: Optional[int] = None
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.log = logging.getLogger(f"bot.{config.name}")

    # ----------------------------------------------------------- state
    @property
    def name(self) -> str:
        return self.config.name

    @property
    def in_position(self) -> bool:
        return self.broker.qty > 0

    def state(self) -> Dict[str, Any]:
        return {
            "strategy": self.config.strategy,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "mode": self.config.mode,
            "starting_balance": self.config.starting_balance,
            "cash": self.broker.cash,
            "qty": self.broker.qty,
            "entry_price": self.entry_price,
            "entry_cost": self.entry_cost,
            "peak_price": self.peak_price,
            "last_candle_time": self.last_candle_time,
        }

    def restore(self, state: Dict[str, Any]) -> None:
        self.broker.cash = state["cash"]
        self.broker.qty = state["qty"]
        self.entry_price = state.get("entry_price")
        self.entry_cost = state.get("entry_cost", 0.0)
        self.peak_price = state.get("peak_price")
        self.last_candle_time = state.get("last_candle_time")

    def _persist(self) -> None:
        if self.storage:
            self.storage.save_state(self.name, self.state())

    # ----------------------------------------------------------- logic
    def on_closed_candles(self, candles: List[Candle], price: Optional[float] = None) -> Signal:
        """Evaluate the strategy on a new closed candle and trade on its signal.

        ``price`` is the execution price (current market price when live,
        candle close in backtests).
        """
        if not candles:
            return Signal.HOLD
        last = candles[-1]
        if last.open_time == self.last_candle_time:
            return Signal.HOLD
        self.last_candle_time = last.open_time
        price = price if price is not None else last.close
        ts = last.close_time

        signal = Signal.HOLD
        if len(candles) >= self.strategy.min_candles:
            signal = self.strategy.generate_signal(candles, self.in_position)

        if signal is Signal.BUY and not self.in_position:
            self._buy(price, ts, reason="signal")
        elif signal is Signal.SELL and self.in_position:
            self._sell(price, ts, reason="signal")

        self.record_equity(ts, last.close)
        self._persist()
        return signal

    def check_risk(self, low: float, high: float, ts: int, open_price: Optional[float] = None) -> Optional[str]:
        """Exit on stop-loss / trailing stop / take-profit.

        Backtests pass the candle's low/high/open; live trading passes the
        current price for all three.
        """
        if not self.in_position or self.entry_price is None:
            return None
        cfg = self.config
        stops = []
        if cfg.stop_loss_pct:
            stops.append(("stop_loss", self.entry_price * (1 - cfg.stop_loss_pct / 100)))
        if cfg.trailing_stop_pct and self.peak_price:
            stops.append(("trailing_stop", self.peak_price * (1 - cfg.trailing_stop_pct / 100)))
        if stops:
            reason, level = max(stops, key=lambda s: s[1])
            if low <= level:
                exit_price = min(level, open_price) if open_price is not None else level
                self._sell(exit_price, ts, reason=reason)
                self._persist()
                return reason
        if cfg.take_profit_pct:
            level = self.entry_price * (1 + cfg.take_profit_pct / 100)
            if high >= level:
                exit_price = max(level, open_price) if open_price is not None else level
                self._sell(exit_price, ts, reason="take_profit")
                self._persist()
                return "take_profit"
        self.peak_price = max(self.peak_price or high, high)
        return None

    def record_equity(self, ts: int, price: float) -> None:
        point = {"ts": ts, "equity": self.broker.equity(price), "price": price, "in_position": self.in_position}
        self.equity_curve.append(point)
        if self.storage:
            self.storage.add_equity(self.name, ts, point["equity"], price, self.in_position)

    # ----------------------------------------------------------- orders
    def _buy(self, price: float, ts: int, reason: str) -> Optional[Fill]:
        equity = self.broker.equity(price)
        amount = min(self.broker.cash, equity * self.config.position_size_pct / 100)
        try:
            fill = self.broker.buy(price, amount)
        except Exception:
            self.log.exception("BUY failed")
            return None
        if fill is None:
            return None
        self.entry_price = fill.price
        self.entry_cost = fill.quote
        self.peak_price = fill.price
        self._record(ts, fill, reason)
        self.log.info("BUY  %.6f %s @ %.4f (%s)", fill.qty, self.config.symbol, fill.price, reason)
        return fill

    def _sell(self, price: float, ts: int, reason: str) -> Optional[Fill]:
        try:
            fill = self.broker.sell(price, self.broker.qty)
        except Exception:
            self.log.exception("SELL failed")
            return None
        if fill is None:
            return None
        proceeds = fill.quote - fill.fee
        pnl = proceeds - self.entry_cost
        pnl_pct = pnl / self.entry_cost * 100 if self.entry_cost else 0.0
        self._record(ts, fill, reason, pnl=pnl, pnl_pct=pnl_pct)
        self.log.info(
            "SELL %.6f %s @ %.4f (%s) pnl=%.2f (%.2f%%)",
            fill.qty, self.config.symbol, fill.price, reason, pnl, pnl_pct,
        )
        if not self.in_position:
            self.entry_price = None
            self.entry_cost = 0.0
            self.peak_price = None
        return fill

    def _record(self, ts: int, fill: Fill, reason: str, pnl: Optional[float] = None, pnl_pct: Optional[float] = None) -> None:
        trade = {
            "ts": ts,
            "side": fill.side,
            "price": fill.price,
            "qty": fill.qty,
            "quote": fill.quote,
            "fee": fill.fee,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
        }
        self.trades.append(trade)
        if self.storage:
            self.storage.add_trade(self.name, trade)
