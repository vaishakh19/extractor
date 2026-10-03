from __future__ import annotations

from datetime import UTC

import pandas as pd
import pytest

from app.backtest.engine import BacktestConfig, BacktestEngine
from app.strategy.base import Strategy
from app.strategy.common import signal_from_last
from app.trading.signal import SignalAction


class ScheduledStrategy(Strategy):
    name = "scheduled"
    warmup_period = 2

    def generate_signal(self, market_data: pd.DataFrame, symbol: str):
        action = SignalAction.HOLD
        if len(market_data) == 3:
            action = SignalAction.BUY
        elif len(market_data) == 5:
            action = SignalAction.SELL
        return signal_from_last(market_data, symbol, self.name, action, "test schedule")


def test_backtest_executes_on_next_candle_open() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=7, freq="5min", tz=UTC),
            "open": [100, 100, 100, 110, 120, 130, 130],
            "high": [101, 101, 101, 111, 121, 131, 131],
            "low": [99, 99, 99, 109, 119, 129, 129],
            "close": [100, 100, 100, 110, 120, 130, 130],
            "volume": [10] * 7,
        }
    )
    config = BacktestConfig(
        "BTC/USDT",
        fee_rate=0,
        slippage_bps=0,
        stop_loss_percent=50,
        take_profit_percent=100,
        max_position_percent=0.25,
    )
    result = BacktestEngine(ScheduledStrategy(), config).run(frame)
    assert result.metrics["total_trades"] == 1
    assert result.trades[0]["entry_price"] == 110  # signal formed at prior close 100
    assert result.trades[0]["exit_price"] == 130  # sell signal formed at prior close 120
    assert result.metrics["net_pnl"] > 0


def test_backtest_rejects_insufficient_data(candles: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="need at least"):
        BacktestEngine(ScheduledStrategy(), BacktestConfig("BTC/USDT")).run(candles.iloc[:2])
