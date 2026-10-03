from __future__ import annotations

import pandas as pd

from app.strategy.base import Strategy
from app.strategy.common import signal_from_last
from app.strategy.indicators import ema, rsi
from app.trading.signal import SignalAction, TradingSignal


class CombinedStrategy(Strategy):
    """EMA crossover confirmed by neutral RSI and above-threshold volume."""

    name = "combined"

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        rsi_period: int = 14,
        oversold: float = 30,
        overbought: float = 70,
        volume_period: int = 20,
        volume_multiplier: float = 1.0,
    ) -> None:
        if fast_period < 2 or slow_period <= fast_period:
            raise ValueError("EMA periods require 2 <= fast < slow")
        if rsi_period < 2 or not 0 <= oversold < overbought <= 100:
            raise ValueError("invalid RSI period or thresholds")
        if volume_period < 2 or volume_multiplier <= 0:
            raise ValueError("invalid volume confirmation parameters")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.volume_period = volume_period
        self.volume_multiplier = volume_multiplier
        self.warmup_period = max(slow_period, rsi_period + 1, volume_period) + 1

    def generate_signal(self, market_data: pd.DataFrame, symbol: str) -> TradingSignal:
        if len(market_data) < self.warmup_period:
            return signal_from_last(
                market_data, symbol, self.name, SignalAction.HOLD, "insufficient combined history"
            )
        fast = ema(market_data["close"], self.fast_period)
        slow = ema(market_data["close"], self.slow_period)
        rsi_values = rsi(market_data["close"], self.rsi_period)
        average_volume = market_data["volume"].rolling(self.volume_period).mean()

        current_rsi = float(rsi_values.iloc[-1])
        current_volume = float(market_data["volume"].iloc[-1])
        volume_floor = float(average_volume.iloc[-1]) * self.volume_multiplier
        volume_confirmed = current_volume >= volume_floor
        crossed_up = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
        crossed_down = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
        metadata = {
            "ema_fast": float(fast.iloc[-1]),
            "ema_slow": float(slow.iloc[-1]),
            "rsi": current_rsi,
            "volume": current_volume,
            "volume_floor": volume_floor,
        }
        if crossed_up and self.oversold < current_rsi < self.overbought and volume_confirmed:
            return signal_from_last(
                market_data,
                symbol,
                self.name,
                SignalAction.BUY,
                "bullish EMA crossover confirmed by RSI and volume",
                metadata,
            )
        if crossed_down and volume_confirmed:
            return signal_from_last(
                market_data,
                symbol,
                self.name,
                SignalAction.SELL,
                "bearish EMA crossover confirmed by volume",
                metadata,
            )
        return signal_from_last(
            market_data,
            symbol,
            self.name,
            SignalAction.HOLD,
            "combined confirmations not satisfied",
            metadata,
        )
