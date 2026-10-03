"""Strategy interface. Strategies create signals and can never submit orders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.trading.signal import TradingSignal


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    parameters: dict[str, Any]


class Strategy(ABC):
    name: str
    warmup_period: int

    @abstractmethod
    def generate_signal(self, market_data: pd.DataFrame, symbol: str) -> TradingSignal:
        """Generate a signal using only the rows supplied by the caller."""
