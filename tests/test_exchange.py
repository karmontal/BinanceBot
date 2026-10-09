import hashlib
import hmac
from urllib.parse import urlencode

from binancebot.exchange import BinanceClient


class Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = str(data)
        self.headers = {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append((method, url, dict(params), dict(headers)))
        return Resp(200, self.data)


def test_klines_parsing_drops_open_candle():
    raw = [
        [0, "1", "2", "0.5", "1.5", "10", 999, "0", 0, "0", "0", "0"],
        [1000, "1.5", "3", "1", "2", "10", 10**15, "0", 0, "0", "0", "0"],  # still open
    ]
    c = BinanceClient(session=FakeSession(raw))
    candles = c.closed_klines("BTCUSDT", "1h", 10)
    assert len(candles) == 1 and candles[0].close == 1.5


def test_signed_order_request():
    s = FakeSession({"ok": True})
    c = BinanceClient(api_key="key", api_secret="secret", session=s)
    c.market_order("BTCUSDT", "BUY", quote_qty="10")
    method, url, params, headers = s.calls[0]
    assert method == "POST" and url.endswith("/api/v3/order")
    assert headers["X-MBX-APIKEY"] == "key"
    sig = params.pop("signature")
    expected = hmac.new(b"secret", urlencode(params).encode(), hashlib.sha256).hexdigest()
    assert sig == expected
    assert params["quoteOrderQty"] == "10" and params["type"] == "MARKET"


class FailingSession:
    def __init__(self):
        self.calls = 0

    def request(self, *a, **kw):
        import requests

        self.calls += 1
        raise requests.ConnectionError("down")


def test_retry_backoff_ends_on_shutdown():
    import threading
    import time

    import pytest

    from binancebot.exchange import BinanceError

    s = FailingSession()
    c = BinanceClient(session=s, max_retries=5)
    threading.Timer(0.2, c.stop_event.set).start()
    started = time.time()
    with pytest.raises(BinanceError):
        c.price("BTCUSDT")
    assert time.time() - started < 2  # would be 2+4+8+10s without the stop event
    assert s.calls == 1
