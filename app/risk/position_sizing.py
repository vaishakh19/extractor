from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PositionSize:
    quantity: float
    notional: float
    risk_amount: float
    stop_distance: float


def calculate_position_size(
    *,
    equity: float,
    available_balance: float,
    entry_price: float,
    stop_loss: float,
    risk_fraction: float,
    max_position_fraction: float,
    fee_rate: float = 0.0,
    minimum_amount: float | None = None,
    minimum_cost: float | None = None,
) -> PositionSize:
    values = [equity, available_balance, entry_price, stop_loss]
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError("equity, balance, entry price, and stop loss must be positive and finite")
    if stop_loss >= entry_price:
        raise ValueError("long stop loss must be below entry price")
    if not 0 < risk_fraction <= 0.1:
        raise ValueError("risk fraction must be in (0, 0.1]")
    if not 0 < max_position_fraction <= 1:
        raise ValueError("max position fraction must be in (0, 1]")
    if not 0 <= fee_rate <= 0.1:
        raise ValueError("invalid fee rate")

    risk_amount = equity * risk_fraction
    stop_distance = entry_price - stop_loss
    by_risk = risk_amount / stop_distance
    by_position = equity * max_position_fraction / entry_price
    by_cash = available_balance / (entry_price * (1 + fee_rate))
    quantity = min(by_risk, by_position, by_cash)
    notional = quantity * entry_price
    if quantity <= 0 or not math.isfinite(quantity):
        raise ValueError("calculated quantity is invalid")
    if minimum_amount is not None and quantity < minimum_amount:
        raise ValueError(f"quantity {quantity:.12g} is below exchange minimum {minimum_amount}")
    if minimum_cost is not None and notional < minimum_cost:
        raise ValueError(f"notional {notional:.12g} is below exchange minimum {minimum_cost}")
    return PositionSize(quantity, notional, risk_amount, stop_distance)
