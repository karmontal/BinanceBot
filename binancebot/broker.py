"""Order execution: a simulated paper broker and a real Binance broker.

Each bot owns one broker and therefore its own isolated budget. With the real
broker several bots share one Binance account, so each bot keeps a *virtual*
sub-account (cash + qty) and only ever sells what it bought itself.
"""
from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from typing import Optional

from .exchange import BinanceClient
from .models import Fill

log = logging.getLogger(__name__)


class Broker(ABC):
    def __init__(self, cash: float, qty: float = 0.0) -> None:
        self.cash = cash
        self.qty = qty

    @abstractmethod
    def buy(self, price: float, quote_amount: float) -> Optional[Fill]:
        """Spend ``quote_amount`` of the quote asset at market."""

    @abstractmethod
    def sell(self, price: float, qty: float) -> Optional[Fill]:
        """Sell ``qty`` of the base asset at market."""

    def equity(self, price: float) -> float:
        return self.cash + self.qty * price


class PaperBroker(Broker):
    """Simulated fills at the given price with fees and slippage."""

    def __init__(self, cash: float, qty: float = 0.0, fee_rate: float = 0.001, slippage_pct: float = 0.05) -> None:
        super().__init__(cash, qty)
        self.fee_rate = fee_rate
        self.slippage = slippage_pct / 100.0

    def buy(self, price: float, quote_amount: float) -> Optional[Fill]:
        quote_amount = min(quote_amount, self.cash)
        if quote_amount <= 0:
            return None
        fill_price = price * (1 + self.slippage)
        fee = quote_amount * self.fee_rate
        qty = (quote_amount - fee) / fill_price
        self.cash -= quote_amount
        self.qty += qty
        return Fill("BUY", fill_price, qty, quote_amount, fee)

    def sell(self, price: float, qty: float) -> Optional[Fill]:
        qty = min(qty, self.qty)
        if qty <= 0:
            return None
        fill_price = price * (1 - self.slippage)
        gross = qty * fill_price
        fee = gross * self.fee_rate
        self.qty -= qty
        if self.qty < 1e-12:
            self.qty = 0.0
        self.cash += gross - fee
        return Fill("SELL", fill_price, qty, gross, fee)


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def _fmt(value: float, decimals: int = 8) -> str:
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


class BinanceBroker(Broker):
    """Real market orders on Binance (live or testnet, depending on the client)."""

    def __init__(self, client: BinanceClient, symbol: str, cash: float, qty: float = 0.0) -> None:
        super().__init__(cash, qty)
        self.client = client
        self.symbol = symbol
        self.filters = client.symbol_filters(symbol)

    def buy(self, price: float, quote_amount: float) -> Optional[Fill]:
        quote_amount = min(quote_amount, self.cash)
        quote_amount = math.floor(quote_amount * 100) / 100  # USDT-style 2 decimals
        if quote_amount < max(self.filters["min_notional"], 0.0) or quote_amount <= 0:
            log.warning("%s: buy of %.2f below min notional, skipped", self.symbol, quote_amount)
            return None
        resp = self.client.market_order(self.symbol, "BUY", quote_qty=_fmt(quote_amount, 2))
        fill = self._parse(resp, "BUY")
        self.cash -= fill.quote
        self.qty += fill.qty
        return fill

    def sell(self, price: float, qty: float) -> Optional[Fill]:
        qty = _floor_to_step(min(qty, self.qty), self.filters["step_size"])
        if qty < self.filters["min_qty"] or qty * price < self.filters["min_notional"]:
            log.warning("%s: sell of %s below exchange minimums, skipped", self.symbol, qty)
            return None
        resp = self.client.market_order(self.symbol, "SELL", quantity=_fmt(qty))
        fill = self._parse(resp, "SELL")
        self.qty = max(self.qty - fill.qty, 0.0)
        # Dust left after step-size rounding cannot be sold; drop it from the books.
        if self.qty < self.filters["min_qty"]:
            self.qty = 0.0
        self.cash += fill.quote - fill.fee
        return fill

    def _parse(self, resp: dict, side: str) -> Fill:
        executed = float(resp["executedQty"])
        quote = float(resp["cummulativeQuoteQty"])
        base_asset = self.filters["base_asset"]
        quote_asset = self.filters["quote_asset"]
        fee_quote = 0.0
        fee_base = 0.0
        for f in resp.get("fills", []):
            commission = float(f["commission"])
            if f["commissionAsset"] == base_asset:
                fee_base += commission
            elif f["commissionAsset"] == quote_asset:
                fee_quote += commission
            else:  # e.g. BNB: estimate its value in quote asset
                fee_quote += float(f["price"]) * float(f["qty"]) * 0.00075
        avg_price = quote / executed if executed else 0.0
        if side == "BUY":
            # Fee taken in base asset reduces the quantity we actually hold.
            return Fill(side, avg_price, executed - fee_base, quote, fee_quote + fee_base * avg_price)
        return Fill(side, avg_price, executed, quote, fee_quote + fee_base * avg_price)
