from __future__ import annotations

import pandas as pd

from app.strategy.base import Strategy
from app.strategy.common import signal_from_last
from app.strategy.indicators import ema
from app.trading.signal import SignalAction, TradingSignal


class EMACrossStrategy(Strategy):
    name = "ema_cross"

    def __init__(self, fast_period: int = 20, slow_period: int = 50) -> None:
        if fast_period < 2 or slow_period <= fast_period:
            raise ValueError("EMA periods require 2 <= fast < slow")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.warmup_period = slow_period + 1

    def generate_signal(self, market_data: pd.DataFrame, symbol: str) -> TradingSignal:
        if len(market_data) < self.warmup_period:
            return signal_from_last(
                market_data, symbol, self.name, SignalAction.HOLD, "insufficient EMA history"
            )
        fast = ema(market_data["close"], self.fast_period)
        slow = ema(market_data["close"], self.slow_period)
        previous_fast, current_fast = fast.iloc[-2], fast.iloc[-1]
        previous_slow, current_slow = slow.iloc[-2], slow.iloc[-1]
        metadata = {"ema_fast": float(current_fast), "ema_slow": float(current_slow)}
        if previous_fast <= previous_slow and current_fast > current_slow:
            return signal_from_last(
                market_data,
                symbol,
                self.name,
                SignalAction.BUY,
                "fast EMA crossed above slow EMA",
                metadata,
            )
        if previous_fast >= previous_slow and current_fast < current_slow:
            return signal_from_last(
                market_data,
                symbol,
                self.name,
                SignalAction.SELL,
                "fast EMA crossed below slow EMA",
                metadata,
            )
        return signal_from_last(
            market_data, symbol, self.name, SignalAction.HOLD, "no EMA crossover", metadata
        )
