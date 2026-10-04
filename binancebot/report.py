"""Comparison tables for backtests and running bots."""
from __future__ import annotations

import csv
import math
import os
from typing import Any, Dict, List

COLUMNS = [
    ("name", "Bot", "{}"),
    ("strategy", "Strategy", "{}"),
    ("total_return_pct", "Return%", "{:+.2f}"),
    ("market_return_pct", "Market%", "{:+.2f}"),
    ("max_drawdown_pct", "MaxDD%", "{:.2f}"),
    ("return_over_dd", "Ret/DD", "{:.2f}"),
    ("sharpe", "Sharpe", "{:.2f}"),
    ("trades", "Trades", "{}"),
    ("win_rate_pct", "Win%", "{:.1f}"),
    ("profit_factor", "PF", "{:.2f}"),
    ("avg_trade_pct", "AvgTrade%", "{:+.2f}"),
    ("fees_paid", "Fees", "{:.2f}"),
    ("exposure_pct", "InMkt%", "{:.0f}"),
    ("final_equity", "Equity", "{:.2f}"),
]


def _fmt(fmt: str, value: Any) -> str:
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return fmt.format(value)


def rows_from_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [{"name": r["name"], "strategy": r["strategy"], **r["metrics"]} for r in results]
    rows.sort(key=lambda r: r["total_return_pct"], reverse=True)
    return rows


def format_table(rows: List[Dict[str, Any]]) -> str:
    header = [c[1] for c in COLUMNS]
    body = [[_fmt(fmt, row[key]) for key, _, fmt in COLUMNS] for row in rows]
    widths = [max(len(h), *(len(b[i]) for b in body)) if body else len(h) for i, h in enumerate(header)]
    line = "  ".join(h.ljust(w) for h, w in zip(header, widths))
    sep = "  ".join("-" * w for w in widths)
    out = [line, sep]
    for b in body:
        out.append("  ".join(v.ljust(w) if i < 2 else v.rjust(w) for i, (v, w) in enumerate(zip(b, widths))))
    return "\n".join(out)


def write_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    keys = [c[0] for c in COLUMNS] + ["open_position"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_trades_csv(path: str, trades: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    keys = ["ts", "side", "price", "qty", "quote", "fee", "pnl", "pnl_pct", "reason"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)
