import pytest

from binancebot.bot import BotConfig, TradingBot
from binancebot.broker import BinanceBroker, PaperBroker
from binancebot.models import Candle, Signal
from binancebot.storage import Storage
from binancebot.strategies import create_strategy


def candle(t, o, h, l, c):
    return Candle(t, o, h, l, c, 1.0, t + 999)


def test_paper_broker_round_trip_costs_fees():
    b = PaperBroker(1000.0, fee_rate=0.001, slippage_pct=0.0)
    buy = b.buy(100.0, 1000.0)
    assert b.cash == 0
    assert buy.qty == pytest.approx(9.99)
    sell = b.sell(100.0, b.qty)
    assert b.qty == 0
    assert b.cash == pytest.approx(999.0 - 0.999)
    assert buy.fee + sell.fee == pytest.approx(1.999)


def _bot(**cfg):
    config = BotConfig(name="t", strategy="buy_and_hold", starting_balance=1000.0, **cfg)
    broker = PaperBroker(1000.0, fee_rate=0.0, slippage_pct=0.0)
    return TradingBot(config, create_strategy("buy_and_hold"), broker)


def test_bot_buys_once_and_ignores_same_candle():
    bot = _bot()
    c = [candle(0, 100, 101, 99, 100)]
    assert bot.on_closed_candles(c) is Signal.BUY
    assert bot.in_position
    assert bot.on_closed_candles(c) is Signal.HOLD  # same candle -> no re-evaluation
    assert len(bot.trades) == 1


def test_stop_loss_and_take_profit():
    bot = _bot(stop_loss_pct=5, take_profit_pct=10)
    bot.on_closed_candles([candle(0, 100, 100, 100, 100)])
    assert bot.check_risk(low=96, high=104, ts=1, open_price=100) is None
    assert bot.check_risk(low=94, high=100, ts=2, open_price=99) == "stop_loss"
    assert bot.trades[-1]["price"] == pytest.approx(95.0)
    assert bot.trades[-1]["pnl_pct"] == pytest.approx(-5.0)

    bot = _bot(take_profit_pct=10)
    bot.on_closed_candles([candle(0, 100, 100, 100, 100)])
    assert bot.check_risk(low=100, high=120, ts=1, open_price=115) == "take_profit"
    assert bot.trades[-1]["price"] == pytest.approx(115.0)  # gapped above target


def test_trailing_stop_follows_peak():
    bot = _bot(trailing_stop_pct=10)
    bot.on_closed_candles([candle(0, 100, 100, 100, 100)])
    assert bot.check_risk(low=100, high=150, ts=1) is None  # peak -> 150
    assert bot.check_risk(low=136, high=140, ts=2) is None  # stop at 135
    assert bot.check_risk(low=130, high=140, ts=3) == "trailing_stop"
    assert bot.trades[-1]["price"] == pytest.approx(135.0)


def test_position_size_pct():
    bot = _bot(position_size_pct=25)
    bot.on_closed_candles([candle(0, 100, 100, 100, 100)])
    assert bot.broker.cash == pytest.approx(750.0)


def test_state_persist_and_restore():
    storage = Storage(":memory:")
    bot = _bot()
    bot.storage = storage
    bot.on_closed_candles([candle(0, 100, 100, 100, 100)])
    state = storage.load_state("t")
    fresh = _bot()
    fresh.restore(state)
    assert fresh.broker.qty == pytest.approx(bot.broker.qty)
    assert fresh.entry_price == 100
    assert fresh.last_candle_time == 0
    assert len(storage.trades("t")) == 1
    assert len(storage.equity_curve("t")) == 1


class FakeClient:
    def __init__(self):
        self.orders = []

    def symbol_filters(self, symbol):
        return {"base_asset": "BTC", "quote_asset": "USDT", "step_size": 0.00001,
                "min_qty": 0.00001, "min_notional": 5.0, "quote_precision": 8}

    def market_order(self, symbol, side, quantity=None, quote_qty=None):
        self.orders.append((side, quantity, quote_qty))
        if side == "BUY":
            q = float(quote_qty)
            qty = q / 50000
            return {"executedQty": str(qty), "cummulativeQuoteQty": str(q),
                    "fills": [{"price": "50000", "qty": str(qty), "commission": str(qty * 0.001), "commissionAsset": "BTC"}]}
        qty = float(quantity)
        return {"executedQty": quantity, "cummulativeQuoteQty": str(qty * 51000),
                "fills": [{"price": "51000", "qty": quantity, "commission": str(qty * 51), "commissionAsset": "USDT"}]}


def test_binance_broker_accounting():
    client = FakeClient()
    b = BinanceBroker(client, "BTCUSDT", cash=100.0)
    fill = b.buy(50000, 100.0)
    assert client.orders[0] == ("BUY", None, "100")
    assert b.cash == pytest.approx(0.0)
    assert fill.qty == pytest.approx(0.002 * 0.999)
    fill = b.sell(51000, b.qty)
    qty_sent = float(client.orders[1][1])
    assert qty_sent <= 0.002 * 0.999
    assert b.qty == 0.0
    assert b.cash == pytest.approx(qty_sent * 51000 * 0.999)


def test_binance_broker_respects_min_notional():
    b = BinanceBroker(FakeClient(), "BTCUSDT", cash=3.0)
    assert b.buy(50000, 3.0) is None
