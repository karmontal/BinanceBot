#!/usr/bin/env python3
"""BinanceBot command line.

    python main.py strategies                 # list strategies + default params
    python main.py backtest --days 180        # compare all bots on history
    python main.py run                        # run all bots in parallel (paper by default)
    python main.py report                     # compare the running bots so far
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from binancebot.backtest import load_candles_csv, run_backtest, save_candles_csv
from binancebot.config import load_config
from binancebot.exchange import BinanceClient
from binancebot.metrics import compute_metrics
from binancebot.report import format_table, rows_from_results, write_csv, write_trades_csv
from binancebot.storage import Storage
from binancebot.strategies import STRATEGIES
from binancebot.synthetic import generate_candles


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _filter(bots, only):
    if not only:
        return bots
    names = set(only.split(","))
    missing = names - {b.name for b in bots}
    if missing:
        raise SystemExit(f"unknown bot(s): {sorted(missing)}")
    return [b for b in bots if b.name in names]


def _parse_date(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def cmd_strategies(args) -> None:
    for name, cls in STRATEGIES.items():
        doc = (cls.__doc__ or "").strip().splitlines()[0]
        print(f"{name:22s} {cls.default_params}\n{'':22s} {doc}")


def cmd_backtest(args) -> None:
    from dataclasses import replace

    from binancebot.bot import lookback_for
    from binancebot.models import interval_ms
    from binancebot.strategies import create_strategy

    settings, bots = load_config(args.config)
    bots = _filter(bots, args.only) if args.only else [b for b in bots if b.enabled]
    overrides = {k: v for k, v in (("interval", args.interval), ("symbol", args.symbol)) if v}
    if overrides:
        suffix = f"@{args.interval}" if args.interval else ""
        bots = [replace(b, name=b.name + suffix, **overrides) for b in bots]
    if not args.verbose:
        logging.getLogger("bot").setLevel(logging.WARNING)  # per-trade logs are noise here
    # Round "now" down to the hour so repeated runs reuse the cached download.
    end_ms = _parse_date(args.end) if args.end else int(time.time() * 1000) // 3_600_000 * 3_600_000
    start_ms = _parse_date(args.start) if args.start else end_ms - args.days * 86_400_000
    client = BinanceClient(settings.market_data_url)
    data = {}
    results = []
    for cfg in bots:
        key = (cfg.symbol, cfg.interval)
        if key not in data:
            if args.synthetic:
                data[key] = (generate_candles(args.synthetic, cfg.interval, seed=args.seed), None)
            elif args.csv:
                data[key] = (load_candles_csv(args.csv), None)
            else:
                # Extra candles before the start so indicators are warmed up on day one.
                warmup = max(
                    lookback_for(create_strategy(b.strategy, b.params), b.trend_filter_ema)
                    for b in bots if (b.symbol, b.interval) == key
                )
                fetch_from = start_ms - warmup * interval_ms(cfg.interval)
                cache = os.path.join("data", "cache", f"{cfg.symbol}_{cfg.interval}_{fetch_from}_{end_ms}.csv")
                if os.path.exists(cache):
                    candles = load_candles_csv(cache)
                else:
                    logging.info("downloading %s %s history...", *key)
                    candles = client.historical_klines(cfg.symbol, cfg.interval, fetch_from, end_ms)
                    save_candles_csv(cache, candles)
                data[key] = (candles, start_ms)
            in_range = sum(1 for c in data[key][0] if data[key][1] is None or c.open_time >= data[key][1])
            logging.info("%s %s: %d candles", *key, in_range)
        candles, trade_from = data[key]
        results.append(run_backtest(cfg, candles, settings.fee_rate, settings.slippage_pct, start_ms=trade_from))

    rows = rows_from_results(results)
    print()
    print(format_table(rows))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out, f"backtest_{stamp}")
    write_csv(os.path.join(out_dir, "summary.csv"), rows)
    for r in results:
        write_trades_csv(os.path.join(out_dir, "trades", f"{r['name']}.csv"), r["trades"])
    print(f"\nSaved to {out_dir}/")


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def cmd_run(args) -> None:
    from binancebot.runner import run

    # `docker stop` / systemd send SIGTERM: shut down as cleanly as on Ctrl+C.
    signal.signal(signal.SIGTERM, _raise_interrupt)

    settings, bots = load_config(args.config)
    bots = _filter(bots, args.only)
    storage = Storage(settings.db_path)
    if args.reset:
        names = [b.name for b in bots] if args.reset == "all" else args.reset.split(",")
        for n in names:
            storage.reset_bot(n)
            logging.info("reset %s", n)
    run(settings, bots, storage)


def cmd_report(args) -> None:
    settings, bots = load_config(args.config)
    storage = Storage(settings.db_path)
    rows = []
    for cfg in _filter(bots, args.only):
        curve = storage.equity_curve(cfg.name)
        if not curve:
            continue
        m = compute_metrics(curve, storage.trades(cfg.name), cfg.starting_balance, cfg.interval)
        rows.append({"name": cfg.name, "strategy": cfg.strategy, **m})
    if not rows:
        print("No data yet. Start the bots with: python main.py run")
        return
    rows.sort(key=lambda r: r["total_return_pct"], reverse=True)
    print(format_table(rows))
    if args.csv:
        write_csv(args.csv, rows)
        print(f"\nSaved to {args.csv}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Multi-strategy Binance trading bots")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("strategies", help="list available strategies")

    b = sub.add_parser("backtest", help="compare bots on historical data")
    b.add_argument("--days", type=int, default=180)
    b.add_argument("--start", help="YYYY-MM-DD (UTC)")
    b.add_argument("--end", help="YYYY-MM-DD (UTC)")
    b.add_argument("--only", help="comma separated bot names")
    b.add_argument("--interval", help="override every bot's interval, e.g. 4h or 1d")
    b.add_argument("--symbol", help="override every bot's symbol, e.g. ETHUSDT")
    b.add_argument("--csv", help="use candles from a CSV file instead of downloading")
    b.add_argument("--synthetic", type=int, metavar="N", help="use N synthetic candles (offline demo)")
    b.add_argument("--seed", type=int, default=42)
    b.add_argument("--out", default="reports")

    r = sub.add_parser("run", help="run bots in parallel (paper/testnet/live)")
    r.add_argument("--only", help="comma separated bot names")
    r.add_argument("--reset", help="wipe saved state of bot names (comma separated) or 'all'")

    rep = sub.add_parser("report", help="performance of the running bots so far")
    rep.add_argument("--only", help="comma separated bot names")
    rep.add_argument("--csv", help="also save the table to this CSV path")

    args = p.parse_args(argv)
    _setup_logging(args.verbose)
    {"strategies": cmd_strategies, "backtest": cmd_backtest, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main(sys.argv[1:])
