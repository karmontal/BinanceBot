"""Run many bots in parallel, one thread per bot."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, List, Tuple

from .backtest import lookback_for
from .bot import BotConfig, TradingBot
from .broker import BinanceBroker, Broker, PaperBroker
from .config import Settings
from .exchange import LIVE_URL, TESTNET_URL, BinanceClient
from .metrics import compute_metrics
from .models import Candle
from .report import format_table
from .storage import Storage
from .strategies import create_strategy

log = logging.getLogger(__name__)


class MarketData:
    """Thread-safe cache so bots on the same symbol share API calls."""

    def __init__(self, client: BinanceClient, ttl: float) -> None:
        self.client = client
        self.ttl = ttl
        self._lock = threading.Lock()
        self._candles: Dict[Tuple[str, str], Tuple[float, int, List[Candle]]] = {}
        self._prices: Dict[str, Tuple[float, float]] = {}

    def closed_klines(self, symbol: str, interval: str, limit: int) -> List[Candle]:
        key = (symbol, interval)
        with self._lock:
            cached = self._candles.get(key)
            if cached and time.time() - cached[0] < self.ttl and cached[1] >= limit:
                return cached[2][-limit:]
        candles = self.client.closed_klines(symbol, interval, limit)
        with self._lock:
            self._candles[key] = (time.time(), limit, candles)
        return candles

    def price(self, symbol: str) -> float:
        with self._lock:
            cached = self._prices.get(symbol)
            if cached and time.time() - cached[0] < self.ttl:
                return cached[1]
        p = self.client.price(symbol)
        with self._lock:
            self._prices[symbol] = (time.time(), p)
        return p


def _trading_client(mode: str) -> BinanceClient:
    if mode == "testnet":
        key, secret = os.environ.get("BINANCE_TESTNET_API_KEY"), os.environ.get("BINANCE_TESTNET_API_SECRET")
        if not (key and secret):
            raise SystemExit("testnet mode needs BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET")
        return BinanceClient(TESTNET_URL, key, secret)
    key, secret = os.environ.get("BINANCE_API_KEY"), os.environ.get("BINANCE_API_SECRET")
    if not (key and secret):
        raise SystemExit("live mode needs BINANCE_API_KEY and BINANCE_API_SECRET")
    if os.environ.get("BINANCE_LIVE_CONFIRM") != "YES":
        raise SystemExit("live mode is locked. Set BINANCE_LIVE_CONFIRM=YES to trade real money.")
    return BinanceClient(LIVE_URL, key, secret)


def build_bots(settings: Settings, configs: List[BotConfig], storage: Storage) -> List[TradingBot]:
    clients: Dict[str, BinanceClient] = {}
    bots = []
    for cfg in configs:
        if not cfg.enabled:
            continue
        state = storage.load_state(cfg.name)
        if state and (state.get("strategy"), state.get("symbol"), state.get("mode")) != (cfg.strategy, cfg.symbol, cfg.mode):
            raise SystemExit(
                f"bot {cfg.name!r} has saved state for a different strategy/symbol/mode. "
                f"Rename it or run with --reset {cfg.name}"
            )
        cash = state["cash"] if state else cfg.starting_balance
        qty = state["qty"] if state else 0.0
        broker: Broker
        if cfg.mode == "paper":
            broker = PaperBroker(cash, qty, fee_rate=settings.fee_rate, slippage_pct=settings.slippage_pct)
        else:
            if cfg.mode not in clients:
                clients[cfg.mode] = _trading_client(cfg.mode)
            broker = BinanceBroker(clients[cfg.mode], cfg.symbol, cash, qty)
        bot = TradingBot(cfg, create_strategy(cfg.strategy, cfg.params), broker, storage)
        if state:
            bot.restore(state)
            log.info("%s: restored state (cash=%.2f qty=%.8f)", cfg.name, bot.broker.cash, bot.broker.qty)
        bots.append(bot)
    _check_real_budgets(bots, clients)
    return bots


def _check_real_budgets(bots: List[TradingBot], clients: Dict[str, BinanceClient]) -> None:
    """Make sure the real account can cover what the real bots think they own."""
    for mode, client in clients.items():
        needed: Dict[str, float] = {}
        for bot in bots:
            if bot.config.mode != mode:
                continue
            f = client.symbol_filters(bot.config.symbol)
            needed[f["quote_asset"]] = needed.get(f["quote_asset"], 0.0) + bot.broker.cash
            needed[f["base_asset"]] = needed.get(f["base_asset"], 0.0) + bot.broker.qty
        balances = {b["asset"]: float(b["free"]) for b in client.account()["balances"]}
        for asset, amount in needed.items():
            if balances.get(asset, 0.0) + 1e-9 < amount:
                raise SystemExit(
                    f"[{mode}] bots need {amount:.8f} {asset} but the account only has "
                    f"{balances.get(asset, 0.0):.8f} free"
                )


def step(bot: TradingBot, market: MarketData) -> None:
    cfg = bot.config
    price = market.price(cfg.symbol)
    now = int(time.time() * 1000)
    bot.check_risk(price, price, now, open_price=price)
    candles = market.closed_klines(cfg.symbol, cfg.interval, lookback_for(bot.strategy))
    bot.on_closed_candles(candles, price=price)


def _bot_loop(bot: TradingBot, market: MarketData, poll: float, stop: threading.Event) -> None:
    bot.log.info("started: %s on %s %s [%s]", bot.strategy, bot.config.symbol, bot.config.interval, bot.config.mode)
    while not stop.is_set():
        try:
            step(bot, market)
        except Exception:
            bot.log.exception("step failed")
        stop.wait(poll)
    bot.log.info("stopped")


def summary(bots: List[TradingBot], storage: Storage) -> str:
    rows = []
    for bot in bots:
        curve = storage.equity_curve(bot.name)
        m = compute_metrics(curve, storage.trades(bot.name), bot.config.starting_balance, bot.config.interval)
        rows.append({"name": bot.name, "strategy": bot.config.strategy, **m})
    rows.sort(key=lambda r: r["total_return_pct"], reverse=True)
    return format_table(rows)


def run(settings: Settings, configs: List[BotConfig], storage: Storage) -> None:
    bots = build_bots(settings, configs, storage)
    if not bots:
        raise SystemExit("no enabled bots")
    market = MarketData(BinanceClient(settings.market_data_url), ttl=max(settings.poll_seconds / 2, 1))
    stop = threading.Event()
    threads = []
    try:
        for i, bot in enumerate(bots):
            t = threading.Thread(
                target=_bot_loop, args=(bot, market, settings.poll_seconds, stop), name=bot.name, daemon=True
            )
            t.start()
            threads.append(t)
            if i < len(bots) - 1:
                time.sleep(0.2)  # stagger API calls
        log.info("%d bots running. Ctrl+C to stop.", len(bots))
        next_summary = time.time() + settings.summary_minutes * 60
        while any(t.is_alive() for t in threads):
            time.sleep(1)
            if time.time() >= next_summary:
                log.info("performance so far:\n%s", summary(bots, storage))
                next_summary = time.time() + settings.summary_minutes * 60
    except KeyboardInterrupt:
        log.info("stopping...")
    finally:
        stop.set()
        market.client.stop_event.set()
        for t in threads:
            t.join(timeout=30)
        log.info("final performance:\n%s", summary(bots, storage))
