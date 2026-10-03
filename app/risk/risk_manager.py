from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.exchange.base import OrderRequest, OrderSide, OrderType
from app.risk.limits import DailyLossLimit, RiskLimits
from app.risk.position_sizing import calculate_position_size
from app.trading.signal import SignalAction, TradingSignal

logger = logging.getLogger("crypto_bot.risk")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reason: str
    order: OrderRequest | None = None
    risk_amount: float = 0.0
    notional: float = 0.0


class RiskManager:
    def __init__(self, limits: RiskLimits, fee_rate: float = 0.001) -> None:
        self.limits = limits
        self.fee_rate = fee_rate
        self.daily = DailyLossLimit(limits.max_daily_loss)

    def assess(
        self,
        signal: TradingSignal,
        *,
        equity: float,
        available_balance: float,
        open_positions: int,
        existing_quantity: float = 0.0,
        market_limits: dict[str, Any] | None = None,
    ) -> RiskDecision:
        if signal.action is SignalAction.HOLD:
            return self._reject("HOLD signals are not orders")
        if equity <= 0 or available_balance < 0 or signal.price <= 0:
            return self._reject("account equity, balance, or signal price is invalid")

        if signal.action is SignalAction.SELL:
            # Risk-reducing exits remain permitted after a daily-loss halt.
            if existing_quantity <= 0:
                return self._reject("no position exists to sell")
            order = OrderRequest(
                signal.symbol,
                OrderSide.SELL,
                existing_quantity,
                OrderType.MARKET,
                client_order_id=f"sig-{signal.signal_id}",
            )
            return RiskDecision(
                True, "risk-reducing exit", order, notional=existing_quantity * signal.price
            )

        if not self.daily.evaluate(equity):
            return self._reject("maximum daily loss reached; new entries halted until next UTC day")
        if open_positions >= self.limits.max_open_positions:
            return self._reject("maximum open positions reached")
        if existing_quantity > 0:
            return self._reject("position already open for this symbol")

        stop_loss = signal.price * (1 - self.limits.stop_loss_percent / 100)
        take_profit = signal.price * (1 + self.limits.take_profit_percent / 100)
        amount_limits = (market_limits or {}).get("amount") or {}
        cost_limits = (market_limits or {}).get("cost") or {}
        try:
            size = calculate_position_size(
                equity=equity,
                available_balance=available_balance,
                entry_price=signal.price,
                stop_loss=stop_loss,
                risk_fraction=self.limits.risk_per_trade,
                max_position_fraction=self.limits.max_position_percent,
                fee_rate=self.fee_rate,
                minimum_amount=_number_or_none(amount_limits.get("min")),
                minimum_cost=_number_or_none(cost_limits.get("min")),
            )
        except ValueError as exc:
            return self._reject(str(exc))
        order = OrderRequest(
            symbol=signal.symbol,
            side=OrderSide.BUY,
            quantity=size.quantity,
            order_type=OrderType.MARKET,
            client_order_id=f"sig-{signal.signal_id}",
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        logger.info(
            "risk approved %s quantity %.12g notional %.2f",
            signal.symbol,
            size.quantity,
            size.notional,
            extra={"event": "risk_approved", "symbol": signal.symbol},
        )
        return RiskDecision(True, "approved", order, size.risk_amount, size.notional)

    def record_realized_pnl(self, value: float) -> None:
        self.daily.record(value)

    @staticmethod
    def _reject(reason: str) -> RiskDecision:
        logger.warning("risk rejected signal: %s", reason, extra={"event": "risk_rejected"})
        return RiskDecision(False, reason)


def _number_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None
