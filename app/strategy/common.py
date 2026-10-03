from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from app.trading.signal import SignalAction, TradingSignal


def signal_from_last(
    frame: pd.DataFrame,
    symbol: str,
    strategy: str,
    action: SignalAction,
    reason: str,
    metadata: dict[str, float] | None = None,
) -> TradingSignal:
    if frame.empty:
        return TradingSignal(
            action=SignalAction.HOLD,
            symbol=symbol,
            strategy=strategy,
            timestamp=datetime.now(UTC),
            price=0,
            reason="no market data",
        )
    last = frame.iloc[-1]
    raw_timestamp = last["timestamp"]
    timestamp = pd.Timestamp(raw_timestamp).to_pydatetime()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return TradingSignal(
        action=action,
        symbol=symbol,
        strategy=strategy,
        timestamp=timestamp,
        price=float(last["close"]),
        reason=reason,
        metadata=metadata or {},
    )
