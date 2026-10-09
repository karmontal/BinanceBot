"""Read-only web dashboard: live bot status, equity curves, trades, backtests."""
from .server import build_server, serve

__all__ = ["build_server", "serve"]
