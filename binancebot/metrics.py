"""Performance metrics used to compare strategies."""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .models import interval_ms

YEAR_MS = 365 * 86_400_000


def compute_metrics(
    equity_curve: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    starting_balance: float,
    interval: str,
) -> Dict[str, Any]:
    equities = [p["equity"] for p in equity_curve]
    final = equities[-1] if equities else starting_balance

    # Max drawdown
    peak = starting_balance
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)

    # Sharpe on per-candle returns, annualised
    rets = [equities[i] / equities[i - 1] - 1 for i in range(1, len(equities)) if equities[i - 1] > 0]
    sharpe = 0.0
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        if sd > 0:
            sharpe = mean / sd * math.sqrt(YEAR_MS / interval_ms(interval))

    closed = [t for t in trades if t["side"] == "SELL" and t.get("pnl") is not None]
    wins = [t for t in closed if t["pnl"] > 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in closed if t["pnl"] <= 0)
    if gross_loss > 0:
        profit_factor = gross_win / gross_loss
    else:
        profit_factor = math.inf if gross_win > 0 else 0.0

    exposure = (
        sum(1 for p in equity_curve if p["in_position"]) / len(equity_curve) * 100 if equity_curve else 0.0
    )
    total_return = (final / starting_balance - 1) * 100 if starting_balance else 0.0
    first_price = equity_curve[0]["price"] if equity_curve else 0.0
    last_price = equity_curve[-1]["price"] if equity_curve else 0.0
    market_return = (last_price / first_price - 1) * 100 if first_price else 0.0

    return {
        "final_equity": final,
        "total_return_pct": total_return,
        "market_return_pct": market_return,
        "max_drawdown_pct": max_dd * 100,
        "return_over_dd": total_return / (max_dd * 100) if max_dd > 0 else (math.inf if total_return > 0 else 0.0),
        "sharpe": sharpe,
        "trades": len(closed),
        "win_rate_pct": len(wins) / len(closed) * 100 if closed else 0.0,
        "profit_factor": profit_factor,
        "avg_trade_pct": sum(t["pnl_pct"] for t in closed) / len(closed) if closed else 0.0,
        "fees_paid": sum(t["fee"] for t in trades),
        "exposure_pct": exposure,
        "open_position": bool(equity_curve and equity_curve[-1]["in_position"]),
    }
