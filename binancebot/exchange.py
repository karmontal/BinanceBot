"""Minimal Binance Spot REST client (market data + signed orders)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from .models import Candle, interval_ms

log = logging.getLogger(__name__)

LIVE_URL = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"
# Public market-data-only mirror; useful where api.binance.com is blocked.
DATA_URL = "https://data-api.binance.vision"


class BinanceError(RuntimeError):
    pass


class BinanceClient:
    def __init__(
        self,
        base_url: str = LIVE_URL,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self._filters_cache: Dict[str, Dict[str, float]] = {}
        # Set on shutdown so retry back-offs end immediately.
        self.stop_event = threading.Event()

    # ------------------------------------------------------------------ http
    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        retries: Optional[int] = None,
    ):
        params = dict(params or {})
        max_retries = retries or self.max_retries
        headers = {}
        if signed:
            if not (self.api_key and self.api_secret):
                raise BinanceError("API key/secret required for signed endpoint")
            headers["X-MBX-APIKEY"] = self.api_key
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            if attempt > 1 and self.stop_event.is_set():
                break
            query = dict(params)
            if signed:
                query["timestamp"] = int(time.time() * 1000)
                query.setdefault("recvWindow", 5000)
                qs = urlencode(query)
                query["signature"] = hmac.new(
                    self.api_secret.encode(), qs.encode(), hashlib.sha256
                ).hexdigest()
            try:
                resp = self.session.request(
                    method, self.base_url + path, params=query, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Binance request failed (%s/%s): %s", attempt, max_retries, exc)
                self.stop_event.wait(min(2**attempt, 10))
                continue
            if resp.status_code in (418, 429) or resp.status_code >= 500:
                last_exc = BinanceError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                wait = float(resp.headers.get("Retry-After", min(2**attempt, 30)))
                log.warning("Binance throttled/unavailable, retrying in %ss", wait)
                self.stop_event.wait(wait)
                continue
            if resp.status_code >= 400:
                # Orders must never be retried blindly on a 4xx.
                raise BinanceError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise BinanceError(f"Binance request failed after {max_retries} attempts: {last_exc}")

    # ----------------------------------------------------------- market data
    def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[Candle]:
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        raw = self._request("GET", "/api/v3/klines", params)
        return [
            Candle(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), int(k[6]))
            for k in raw
        ]

    def closed_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Candle]:
        """Klines with the still-forming last candle removed."""
        candles = self.klines(symbol, interval, limit=min(limit + 1, 1000))
        now = int(time.time() * 1000)
        return [c for c in candles if c.close_time < now][-limit:]

    def historical_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> List[Candle]:
        step = interval_ms(interval)
        out: List[Candle] = []
        cursor = start_ms
        while cursor < end_ms:
            batch = self.klines(symbol, interval, limit=1000, start_time=cursor, end_time=end_ms)
            if not batch:
                break
            out.extend(batch)
            cursor = batch[-1].open_time + step
            if len(batch) < 1000:
                break
        now = int(time.time() * 1000)
        return [c for c in out if c.close_time < now]

    def price(self, symbol: str) -> float:
        return float(self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})["price"])

    def symbol_filters(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self._filters_cache:
            info = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]
            f = {x["filterType"]: x for x in info["filters"]}
            notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
            self._filters_cache[symbol] = {
                "base_asset": info["baseAsset"],
                "quote_asset": info["quoteAsset"],
                "step_size": float(f["LOT_SIZE"]["stepSize"]),
                "min_qty": float(f["LOT_SIZE"]["minQty"]),
                "min_notional": float(notional.get("minNotional", 0.0)),
                "quote_precision": int(info.get("quoteAssetPrecision", 8)),
            }
        return self._filters_cache[symbol]

    # ------------------------------------------------------------ trading
    def account(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v3/account", signed=True)

    def market_order(
        self,
        symbol: str,
        side: str,
        quantity: Optional[str] = None,
        quote_qty: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": symbol, "side": side, "type": "MARKET", "newOrderRespType": "FULL"}
        if quantity is not None:
            params["quantity"] = quantity
        elif quote_qty is not None:
            params["quoteOrderQty"] = quote_qty
        else:
            raise ValueError("quantity or quote_qty required")
        # Single attempt: never risk sending a duplicate order.
        return self._request("POST", "/api/v3/order", params, signed=True, retries=1)
