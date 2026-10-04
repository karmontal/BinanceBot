from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from ..models import Candle, Signal


class Strategy(ABC):
    """Base class for all strategies.

    A strategy only sees *closed* candles and whether the bot currently holds a
    position, and answers BUY / SELL / HOLD. Position sizing, fees and
    stop-loss / take-profit are handled by the bot, not the strategy.
    """

    name: str = "base"
    default_params: Dict[str, Any] = {}

    def __init__(self, **params: Any) -> None:
        unknown = set(params) - set(self.default_params)
        if unknown:
            raise ValueError(f"{self.name}: unknown params {sorted(unknown)}")
        self.params: Dict[str, Any] = {**self.default_params, **params}

    @property
    @abstractmethod
    def min_candles(self) -> int:
        """Number of closed candles needed before signals are meaningful."""

    @abstractmethod
    def generate_signal(self, candles: List[Candle], in_position: bool) -> Signal:
        ...

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.params})"


def closes(candles: List[Candle]) -> List[float]:
    return [c.close for c in candles]
