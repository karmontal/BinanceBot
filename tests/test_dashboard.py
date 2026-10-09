import base64
import json
import threading
import urllib.error
import urllib.request

import pytest

from binancebot.bot import BotConfig, TradingBot
from binancebot.broker import PaperBroker
from binancebot.dashboard.data import DashboardData
from binancebot.dashboard.server import build_server
from binancebot.models import Candle
from binancebot.storage import Storage
from binancebot.strategies import create_strategy

CONFIG = """
mode: paper
db_path: {db}
defaults: {{symbol: BTCUSDT, interval: 4h, starting_balance: 1000}}
bots:
  - {{name: bh, strategy: buy_and_hold}}
  - {{name: donchian, strategy: donchian_breakout}}
  - {{name: off, strategy: macd_cross, enabled: false}}
"""


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / "bots.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(CONFIG.format(db=db))
    storage = Storage(str(db))
    bot = TradingBot(BotConfig(name="bh", strategy="buy_and_hold"), create_strategy("buy_and_hold"),
                     PaperBroker(1000.0, fee_rate=0, slippage_pct=0), storage)
    bot.on_closed_candles([Candle(0, 100, 100, 100, 100, 1, 999)])
    storage.heartbeat("bh", 10**13, price=110.0, equity=1100.0, in_position=True)
    storage.heartbeat("donchian", 10**13, error="BinanceError: boom")
    reports = tmp_path / "reports" / "backtest_20260101_000000"
    reports.mkdir(parents=True)
    (reports / "summary.csv").write_text("name,strategy,total_return_pct,profit_factor\nbh,buy_and_hold,12.5,inf\n")
    return DashboardData(str(cfg_path), str(tmp_path / "reports"))


def test_overview(setup):
    data = setup.overview()
    bots = {b["name"]: b for b in data["bots"]}
    assert set(bots) == {"bh", "donchian"}  # disabled + never run is hidden
    bh = bots["bh"]
    assert bh["in_position"] and bh["entry_price"] == 100
    assert bh["equity"] == 1100.0 and bh["return_pct"] == pytest.approx(10.0)
    assert bh["unrealized_pct"] == pytest.approx(10.0)
    assert bh["market_return_pct"] == pytest.approx(10.0)
    assert bh["metrics"]["trades"] == 0
    assert bots["donchian"]["error"] == "BinanceError: boom"
    assert not bots["donchian"]["started"]
    json.dumps(data, allow_nan=False)  # browser-safe JSON


def test_bot_detail_and_backtests(setup):
    detail = setup.bot_detail("bh")
    assert len(detail["equity"]) == 1 and detail["trades"][0]["side"] == "BUY"
    assert setup.bot_detail("missing") is None
    runs = setup.backtests()
    assert runs[0]["rows"][0]["total_return_pct"] == 12.5
    assert runs[0]["rows"][0]["profit_factor"] is None  # inf -> null


def test_overview_without_db(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(CONFIG.format(db=tmp_path / "none.db"))
    data = DashboardData(str(cfg), str(tmp_path / "reports"))
    assert [b["started"] for b in data.overview()["bots"]] == [False, False]
    assert data.backtests() == []


def _serve(data, password=None):
    server = build_server("127.0.0.1", 0, data, password)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_http_endpoints(setup):
    server, base = _serve(setup)
    try:
        assert b"<html" in urllib.request.urlopen(base + "/").read()
        assert b"Chart.js" in urllib.request.urlopen(base + "/static/chart.umd.js").read(200)
        ov = json.load(urllib.request.urlopen(base + "/api/overview"))
        assert len(ov["bots"]) == 2
        assert json.load(urllib.request.urlopen(base + "/api/bot?name=bh"))["name"] == "bh"
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/bot?name=nope")
        assert e.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/../config.yaml")
        assert e.value.code == 404
    finally:
        server.shutdown()


def test_password_protection(setup):
    server, base = _serve(setup, password="s3cret")
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/overview")
        assert e.value.code == 401
        req = urllib.request.Request(base + "/api/overview")
        req.add_header("Authorization", "Basic " + base64.b64encode(b"me:wrong").decode())
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(req)
        req = urllib.request.Request(base + "/api/overview")
        req.add_header("Authorization", "Basic " + base64.b64encode(b"me:s3cret").decode())
        assert urllib.request.urlopen(req).status == 200
    finally:
        server.shutdown()


def test_heartbeat_keeps_last_price_on_error(tmp_path):
    st = Storage(str(tmp_path / "h.db"))
    st.heartbeat("a", 1, price=10.0, equity=100.0, in_position=False)
    st.heartbeat("a", 2, error="boom")
    hb = st.heartbeats()["a"]
    assert (hb["ts"], hb["price"], hb["error"]) == (2, 10.0, "boom")
    st.heartbeat("a", 3, price=11.0, equity=101.0, in_position=True)
    assert st.heartbeats()["a"]["error"] is None
