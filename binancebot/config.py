"""Load ``config.yaml`` into global settings + a list of BotConfig."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, List

import yaml

from .bot import BotConfig
from .strategies import create_strategy

BOT_FIELDS = {f.name for f in fields(BotConfig)}


@dataclass
class Settings:
    mode: str = "paper"
    market_data_url: str = "https://api.binance.com"
    poll_seconds: float = 30.0
    summary_minutes: float = 60.0
    fee_rate: float = 0.001
    slippage_pct: float = 0.05
    db_path: str = "data/bots.db"


def load_config(path: str):
    with open(path, encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    settings = Settings(**{k: v for k, v in raw.items() if k in Settings.__dataclass_fields__})
    defaults = dict(raw.get("defaults") or {})
    defaults.setdefault("mode", settings.mode)

    bots: List[BotConfig] = []
    seen = set()
    for entry in raw.get("bots") or []:
        merged = {**defaults, **entry}
        unknown = set(merged) - BOT_FIELDS
        if unknown:
            raise ValueError(f"bot {merged.get('name')!r}: unknown keys {sorted(unknown)}")
        cfg = BotConfig(**merged)
        if cfg.name in seen:
            raise ValueError(f"duplicate bot name {cfg.name!r}")
        seen.add(cfg.name)
        create_strategy(cfg.strategy, cfg.params)  # validate early
        bots.append(cfg)
    if not bots:
        raise ValueError("config has no bots")
    return settings, bots
