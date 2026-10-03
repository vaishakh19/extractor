from __future__ import annotations

import pandas as pd
import pytest

from app.strategy.ema_cross import EMACrossStrategy
from app.trading.signal import SignalAction


def test_ema_buy_signal(monkeypatch: pytest.MonkeyPatch, candles: pd.DataFrame) -> None:
    strategy = EMACrossStrategy(2, 3)
    outputs = iter([pd.Series([0.0] * 78 + [9.0, 11.0]), pd.Series([0.0] * 78 + [10.0, 10.0])])
    monkeypatch.setattr("app.strategy.ema_cross.ema", lambda *_: next(outputs))
    assert strategy.generate_signal(candles, "BTC/USDT").action is SignalAction.BUY


def test_ema_sell_signal(monkeypatch: pytest.MonkeyPatch, candles: pd.DataFrame) -> None:
    strategy = EMACrossStrategy(2, 3)
    outputs = iter([pd.Series([0.0] * 78 + [11.0, 9.0]), pd.Series([0.0] * 78 + [10.0, 10.0])])
    monkeypatch.setattr("app.strategy.ema_cross.ema", lambda *_: next(outputs))
    assert strategy.generate_signal(candles, "BTC/USDT").action is SignalAction.SELL


def test_ema_hold_signal(monkeypatch: pytest.MonkeyPatch, candles: pd.DataFrame) -> None:
    strategy = EMACrossStrategy(2, 3)
    outputs = iter([pd.Series([0.0] * 78 + [11.0, 12.0]), pd.Series([0.0] * 78 + [10.0, 10.0])])
    monkeypatch.setattr("app.strategy.ema_cross.ema", lambda *_: next(outputs))
    assert strategy.generate_signal(candles, "BTC/USDT").action is SignalAction.HOLD
