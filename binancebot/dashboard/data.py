"""Collects everything the dashboard shows from the SQLite db, config and reports/."""
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..bot import BotConfig
from ..config import load_config
from ..metrics import compute_metrics

ALIVE_SECONDS = 180  # a bot that has not polled for this long is shown as stopped
MAX_POINTS = 1500  # downsample equity curves sent to the browser


def _clean(value: Any) -> Any:
    """JSON has no inf/nan."""
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


class DashboardData:
    def __init__(self, config_path: str, reports_dir: str = "reports") -> None:
        self.config_path = config_path
        self.reports_dir = reports_dir

    # ------------------------------------------------------------ helpers
    def _settings_and_bots(self):
        settings, bots = load_config(self.config_path)
        return settings, {b.name: b for b in bots}

    def _connect(self, db_path: str) -> Optional[sqlite3.Connection]:
        if not os.path.exists(db_path):
            return None
        conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _rows(conn: sqlite3.Connection, sql: str, args=()) -> List[Dict[str, Any]]:
        try:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
        except sqlite3.OperationalError:  # table not created yet (older db)
            return []

    # ------------------------------------------------------------ api
    def overview(self) -> Dict[str, Any]:
        settings, configs = self._settings_and_bots()
        now = time.time()
        conn = self._connect(settings.db_path)
        states, beats, last_points, trades_by_bot = {}, {}, {}, {}
        if conn:
            with conn:
                states = {r["bot"]: json.loads(r["data"]) for r in self._rows(conn, "SELECT * FROM state")}
                beats = {r["bot"]: r for r in self._rows(conn, "SELECT * FROM heartbeat")}
                for r in self._rows(conn, "SELECT * FROM trades ORDER BY ts, id"):
                    trades_by_bot.setdefault(r["bot"], []).append(r)
                curves: Dict[str, List[Dict[str, Any]]] = {}
                for r in self._rows(conn, "SELECT * FROM equity ORDER BY ts"):
                    curves.setdefault(r["bot"], []).append(r)
            conn.close()
        else:
            curves = {}

        names = list(configs) + sorted(set(states) - set(configs))
        bots = []
        for name in names:
            cfg: Optional[BotConfig] = configs.get(name)
            state = states.get(name)
            if cfg is None and state is None:
                continue
            if cfg is not None and not cfg.enabled and state is None:
                continue  # disabled and never ran: nothing to show
            start = cfg.starting_balance if cfg else state.get("starting_balance", 0.0)
            interval = cfg.interval if cfg else state.get("interval", "1h")
            curve = curves.get(name, [])
            trades = trades_by_bot.get(name, [])
            beat = beats.get(name)
            m = compute_metrics(curve, trades, start, interval) if curve else None

            live_equity = beat["equity"] if beat and beat.get("equity") is not None else (m["final_equity"] if m else start)
            live_price = beat.get("price") if beat else None
            first_price = curve[0]["price"] if curve else None
            in_position = bool(state and state.get("qty", 0) > 0)
            entry = state.get("entry_price") if state else None
            last_seen = beat["ts"] / 1000 if beat else None
            bots.append(
                {
                    "name": name,
                    "strategy": cfg.strategy if cfg else state.get("strategy"),
                    "params": cfg.params if cfg else {},
                    "symbol": cfg.symbol if cfg else state.get("symbol"),
                    "interval": interval,
                    "mode": cfg.mode if cfg else state.get("mode"),
                    "enabled": bool(cfg and cfg.enabled),
                    "trend_filter_ema": cfg.trend_filter_ema if cfg else None,
                    "stop_loss_pct": cfg.stop_loss_pct if cfg else None,
                    "take_profit_pct": cfg.take_profit_pct if cfg else None,
                    "trailing_stop_pct": cfg.trailing_stop_pct if cfg else None,
                    "starting_balance": start,
                    "started": bool(state),
                    "equity": live_equity,
                    "return_pct": (live_equity / start - 1) * 100 if start else 0.0,
                    "market_return_pct": (live_price / first_price - 1) * 100 if live_price and first_price else None,
                    "price": live_price,
                    "in_position": in_position,
                    "entry_price": entry,
                    "unrealized_pct": (live_price / entry - 1) * 100 if in_position and entry and live_price else None,
                    "last_seen": last_seen,
                    "alive": bool(last_seen and now - last_seen < ALIVE_SECONDS),
                    "error": beat.get("error") if beat else None,
                    "last_trade": trades[-1] if trades else None,
                    "metrics": m,
                }
            )
        return _clean({"mode": settings.mode, "generated_at": now, "alive_seconds": ALIVE_SECONDS, "bots": bots})

    def bot_detail(self, name: str) -> Optional[Dict[str, Any]]:
        settings, _ = self._settings_and_bots()
        conn = self._connect(settings.db_path)
        if not conn:
            return None
        with conn:
            curve = self._rows(conn, "SELECT ts, equity, price, in_position FROM equity WHERE bot = ? ORDER BY ts", (name,))
            trades = self._rows(conn, "SELECT * FROM trades WHERE bot = ? ORDER BY ts, id", (name,))
        conn.close()
        if not curve and not trades:
            return None
        if len(curve) > MAX_POINTS:
            step = math.ceil(len(curve) / MAX_POINTS)
            curve = curve[::step] + ([curve[-1]] if (len(curve) - 1) % step else [])
        return _clean({"name": name, "equity": curve, "trades": trades})

    def backtests(self, limit: int = 30) -> List[Dict[str, Any]]:
        if not os.path.isdir(self.reports_dir):
            return []
        runs = sorted((d for d in os.listdir(self.reports_dir) if d.startswith("backtest_")), reverse=True)[:limit]
        out = []
        for run in runs:
            path = os.path.join(self.reports_dir, run, "summary.csv")
            if not os.path.exists(path):
                continue
            with open(path, newline="") as fh:
                rows = list(csv.DictReader(fh))
            for row in rows:
                for k, v in row.items():
                    if k in ("name", "strategy"):
                        continue
                    try:
                        row[k] = float(v)
                    except (TypeError, ValueError):
                        pass
            out.append({"id": run, "rows": rows})
        return _clean(out)
