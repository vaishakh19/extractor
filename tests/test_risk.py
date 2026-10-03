from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.risk.limits import RiskLimits
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_manager import RiskManager
from app.trading.signal import SignalAction, TradingSignal


def buy_signal(price: float = 100) -> TradingSignal:
    return TradingSignal(SignalAction.BUY, "BTC/USDT", "test", datetime.now(UTC), price, "test")


def manager() -> RiskManager:
    return RiskManager(RiskLimits(0.01, 0.03, 3, 0.25, 1, 2))


def test_position_sizing_is_limited_by_max_position() -> None:
    size = calculate_position_size(
        equity=1000,
        available_balance=1000,
        entry_price=100,
        stop_loss=99,
        risk_fraction=0.01,
        max_position_fraction=0.25,
    )
    assert size.quantity == pytest.approx(2.5)
    assert size.notional == pytest.approx(250)


def test_risk_rejects_max_positions() -> None:
    decision = manager().assess(buy_signal(), equity=1000, available_balance=1000, open_positions=3)
    assert not decision.approved
    assert "maximum open" in decision.reason


def test_risk_daily_loss_stops_entries_but_not_exit() -> None:
    risk = manager()
    risk.daily.refresh(1000)
    risk.record_realized_pnl(-31)
    rejected = risk.assess(buy_signal(), equity=969, available_balance=969, open_positions=0)
    assert not rejected.approved
    sell = TradingSignal(SignalAction.SELL, "BTC/USDT", "test", datetime.now(UTC), 99, "exit")
    approved = risk.assess(
        sell, equity=969, available_balance=969, open_positions=1, existing_quantity=1
    )
    assert approved.approved


def test_risk_rejects_below_exchange_minimum() -> None:
    decision = manager().assess(
        buy_signal(1),
        equity=10,
        available_balance=10,
        open_positions=0,
        market_limits={"cost": {"min": 100}},
    )
    assert not decision.approved
    assert "minimum" in decision.reason
