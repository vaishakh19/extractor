from __future__ import annotations

import pandas as pd

from app.strategy.base import Strategy
from app.strategy.common import signal_from_last
from app.strategy.indicators import rsi
from app.trading.signal import SignalAction, TradingSignal


class RSIStrategy(Strategy):
    name = "rsi"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70) -> None:
        if period < 2 or not 0 <= oversold < overbought <= 100:
            raise ValueError("RSI requires period >= 2 and 0 <= oversold < overbought <= 100")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.warmup_period = period + 2

    def generate_signal(self, market_data: pd.DataFrame, symbol: str) -> TradingSignal:
        if len(market_data) < self.warmup_period:
            return signal_from_last(
                market_data, symbol, self.name, SignalAction.HOLD, "insufficient RSI history"
            )
        values = rsi(market_data["close"], self.period)
        previous, current = float(values.iloc[-2]), float(values.iloc[-1])
        metadata = {"rsi": current}
        if previous <= self.oversold < current:
            return signal_from_last(
                market_data,
                symbol,
                self.name,
                SignalAction.BUY,
                "RSI recovered above oversold",
                metadata,
            )
        if previous >= self.overbought > current:
            return signal_from_last(
                market_data,
                symbol,
                self.name,
                SignalAction.SELL,
                "RSI fell below overbought",
                metadata,
            )
        return signal_from_last(
            market_data, symbol, self.name, SignalAction.HOLD, "RSI has no threshold exit", metadata
        )
