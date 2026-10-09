"""SQLite persistence for trades, equity snapshots and bot state."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot TEXT NOT NULL,
    ts INTEGER NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    quote REAL NOT NULL,
    fee REAL NOT NULL,
    pnl REAL,
    pnl_pct REAL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    bot TEXT NOT NULL,
    ts INTEGER NOT NULL,
    equity REAL NOT NULL,
    price REAL NOT NULL,
    in_position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    bot TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS heartbeat (
    bot TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    price REAL,
    equity REAL,
    in_position INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot, ts);
CREATE INDEX IF NOT EXISTS idx_equity_bot ON equity(bot, ts);
"""


class Storage:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                # WAL lets the dashboard read while the bots write.
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    def add_trade(self, bot: str, trade: Dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO trades (bot, ts, side, price, qty, quote, fee, pnl, pnl_pct, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bot,
                    trade["ts"],
                    trade["side"],
                    trade["price"],
                    trade["qty"],
                    trade["quote"],
                    trade["fee"],
                    trade.get("pnl"),
                    trade.get("pnl_pct"),
                    trade.get("reason"),
                ),
            )

    def add_equity(self, bot: str, ts: int, equity: float, price: float, in_position: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO equity (bot, ts, equity, price, in_position) VALUES (?, ?, ?, ?, ?)",
                (bot, ts, equity, price, int(in_position)),
            )

    def save_state(self, bot: str, state: Dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO state (bot, data) VALUES (?, ?) ON CONFLICT(bot) DO UPDATE SET data=excluded.data",
                (bot, json.dumps(state)),
            )

    def heartbeat(
        self,
        bot: str,
        ts: int,
        price: Optional[float] = None,
        equity: Optional[float] = None,
        in_position: Optional[bool] = None,
        error: Optional[str] = None,
    ) -> None:
        """Latest liveness info per bot (overwritten every poll)."""
        with self._lock, self._conn:
            if error is None:
                self._conn.execute(
                    "INSERT INTO heartbeat (bot, ts, price, equity, in_position, error) VALUES (?, ?, ?, ?, ?, NULL)"
                    " ON CONFLICT(bot) DO UPDATE SET ts=excluded.ts, price=excluded.price,"
                    " equity=excluded.equity, in_position=excluded.in_position, error=NULL",
                    (bot, ts, price, equity, None if in_position is None else int(in_position)),
                )
            else:
                # Keep the last good price/equity; just record the failure.
                self._conn.execute(
                    "INSERT INTO heartbeat (bot, ts, error) VALUES (?, ?, ?)"
                    " ON CONFLICT(bot) DO UPDATE SET ts=excluded.ts, error=excluded.error",
                    (bot, ts, error[:500]),
                )

    def heartbeats(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM heartbeat").fetchall()
        return {r["bot"]: dict(r) for r in rows}

    def load_state(self, bot: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT data FROM state WHERE bot = ?", (bot,)).fetchone()
        return json.loads(row["data"]) if row else None

    def bots(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute("SELECT bot FROM state ORDER BY bot").fetchall()
        return [r["bot"] for r in rows]

    def trades(self, bot: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM trades WHERE bot = ? ORDER BY ts, id", (bot,)).fetchall()
        return [dict(r) for r in rows]

    def equity_curve(self, bot: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM equity WHERE bot = ? ORDER BY ts", (bot,)).fetchall()
        return [dict(r) for r in rows]

    def reset_bot(self, bot: str) -> None:
        with self._lock, self._conn:
            for table in ("trades", "equity", "state", "heartbeat"):
                self._conn.execute(f"DELETE FROM {table} WHERE bot = ?", (bot,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
