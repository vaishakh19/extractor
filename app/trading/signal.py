from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class TradingSignal:
    action: SignalAction
    symbol: str
    strategy: str
    timestamp: datetime
    price: float
    reason: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    signal_id: str = ""

    def __post_init__(self) -> None:
        timestamp = self.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
            object.__setattr__(self, "timestamp", timestamp)
        if not self.signal_id:
            text = f"{self.strategy}|{self.symbol}|{timestamp.isoformat()}|{self.action.value}"
            object.__setattr__(self, "signal_id", hashlib.sha256(text.encode()).hexdigest()[:32])
