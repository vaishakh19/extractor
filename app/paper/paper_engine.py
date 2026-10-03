"""Local paper broker. This module has no exchange order client by design."""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.exchange.base import InvalidOrder, OrderRequest, OrderSide, OrderType, Ticker
from app.utils.helpers import positive_decimal, split_symbol, validate_symbol


@dataclass(slots=True)
class PaperPosition:
    symbol: str
    quantity: float
    average_entry: float
    entry_fees: float
    opened_at: datetime
    stop_loss: float | None = None
    take_profit: float | None = None
    current_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.average_entry) * self.quantity - self.entry_fees


@dataclass(slots=True)
class PaperOrder:
    id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    filled: float
    remaining: float
    status: str
    requested_price: float | None
    average_fill: float | None
    fee: float
    client_order_id: str | None
    created_at: datetime
    updated_at: datetime
    fills: list[dict[str, Any]] = field(default_factory=list)


class PaperEngine:
    """Simulate spot orders, balances, fees, slippage, limits, and partial fills."""

    def __init__(
        self,
        initial_balance: float = 1000.0,
        quote_currency: str = "USDT",
        fee_rate: float = 0.001,
        slippage_bps: float = 5.0,
        partial_fill_ratio: float = 1.0,
    ) -> None:
        positive_decimal(initial_balance, "initial_balance")
        if not 0 <= fee_rate <= 0.1:
            raise ValueError("fee_rate must be between 0 and 0.1")
        if not 0 <= slippage_bps <= 1000:
            raise ValueError("slippage_bps must be between 0 and 1000")
        if not 0 < partial_fill_ratio <= 1:
            raise ValueError("partial_fill_ratio must be in (0, 1]")
        self.initial_balance = float(initial_balance)
        self.quote_currency = quote_currency.upper()
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.partial_fill_ratio = partial_fill_ratio
        self.cash = float(initial_balance)
        self.positions: dict[str, PaperPosition] = {}
        self.orders: dict[str, PaperOrder] = {}
        self.realized_pnl = 0.0
        self.total_fees = 0.0
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()
        self._client_ids: dict[str, str] = {}

    async def submit_order(self, request: OrderRequest, ticker: Ticker) -> PaperOrder:
        """Submit locally. No object in this class can contact an order endpoint."""
        async with self._lock:
            self._validate_request(request, ticker)
            if request.client_order_id and request.client_order_id in self._client_ids:
                return self.orders[self._client_ids[request.client_order_id]]
            now = datetime.now(UTC)
            order_id = f"paper-{next(self._ids):010d}"
            order = PaperOrder(
                id=order_id,
                symbol=request.symbol,
                side=request.side.value,
                order_type=request.order_type.value,
                quantity=request.quantity,
                filled=0.0,
                remaining=request.quantity,
                status="open",
                requested_price=request.price,
                average_fill=None,
                fee=0.0,
                client_order_id=request.client_order_id,
                created_at=now,
                updated_at=now,
            )
            self.orders[order_id] = order
            if request.client_order_id:
                self._client_ids[request.client_order_id] = order_id

            if request.order_type is OrderType.MARKET:
                fill_quantity = request.quantity * self.partial_fill_ratio
                fill_price = self._market_fill_price(request.side, ticker)
                self._apply_fill(order, fill_quantity, fill_price, request)
                if order.remaining > 1e-12:
                    # Market remainder is cancelled rather than retried/duplicated.
                    order.status = "partially_filled_cancelled"
            elif self._limit_is_marketable(request, ticker):
                self._apply_fill(
                    order,
                    request.quantity * self.partial_fill_ratio,
                    float(request.price),
                    request,
                )
            return order

    async def process_ticker(self, ticker: Ticker) -> list[PaperOrder]:
        """Update marks, fill crossing limit orders, and apply stop/take exits."""
        async with self._lock:
            completed: list[PaperOrder] = []
            position = self.positions.get(ticker.symbol)
            if position:
                position.current_price = ticker.last

            for order in list(self.orders.values()):
                if order.symbol != ticker.symbol or order.status not in {
                    "open",
                    "partially_filled",
                }:
                    continue
                side = OrderSide(order.side)
                if order.order_type == OrderType.LIMIT.value:
                    request = OrderRequest(
                        symbol=order.symbol,
                        side=side,
                        quantity=order.remaining,
                        order_type=OrderType.LIMIT,
                        price=order.requested_price,
                        client_order_id=order.client_order_id,
                    )
                    if self._limit_is_marketable(request, ticker):
                        amount = min(order.remaining, order.quantity * self.partial_fill_ratio)
                        self._apply_fill(order, amount, float(order.requested_price), request)
                        completed.append(order)

            position = self.positions.get(ticker.symbol)
            if position and position.quantity > 0:
                exit_reason = None
                if position.stop_loss is not None and ticker.last <= position.stop_loss:
                    exit_reason = "stop_loss"
                elif position.take_profit is not None and ticker.last >= position.take_profit:
                    exit_reason = "take_profit"
                if exit_reason:
                    request = OrderRequest(
                        symbol=ticker.symbol,
                        side=OrderSide.SELL,
                        quantity=position.quantity,
                        order_type=OrderType.MARKET,
                        client_order_id=f"paper-{exit_reason}-{int(ticker.timestamp.timestamp())}",
                    )
                    order_id = f"paper-{next(self._ids):010d}"
                    now = datetime.now(UTC)
                    order = PaperOrder(
                        id=order_id,
                        symbol=ticker.symbol,
                        side="sell",
                        order_type="market",
                        quantity=position.quantity,
                        filled=0,
                        remaining=position.quantity,
                        status="open",
                        requested_price=None,
                        average_fill=None,
                        fee=0,
                        client_order_id=request.client_order_id,
                        created_at=now,
                        updated_at=now,
                    )
                    self.orders[order_id] = order
                    # Risk exits fill completely in this model to avoid leaving unsafe dust.
                    self._apply_fill(
                        order,
                        request.quantity,
                        self._market_fill_price(request.side, ticker),
                        request,
                    )
                    order.fills[-1]["reason"] = exit_reason
                    completed.append(order)
            return completed

    async def cancel_order(self, order_id: str) -> PaperOrder:
        async with self._lock:
            try:
                order = self.orders[order_id]
            except KeyError as exc:
                raise InvalidOrder(f"unknown paper order {order_id}") from exc
            if order.status in {"open", "partially_filled"}:
                order.status = "cancelled"
                order.updated_at = datetime.now(UTC)
            return order

    def _validate_request(self, request: OrderRequest, ticker: Ticker) -> None:
        validate_symbol(request.symbol)
        if request.symbol != ticker.symbol:
            raise InvalidOrder("ticker symbol does not match order symbol")
        positive_decimal(request.quantity, "quantity")
        _, quote = split_symbol(request.symbol)
        if quote != self.quote_currency:
            raise InvalidOrder(
                f"paper account quote currency is {self.quote_currency}, not {quote}"
            )
        if request.order_type is OrderType.LIMIT:
            if request.price is None:
                raise InvalidOrder("limit order requires a price")
            positive_decimal(request.price, "price")
        if request.side is OrderSide.SELL:
            position = self.positions.get(request.symbol)
            if not position or request.quantity > position.quantity + 1e-12:
                raise InvalidOrder("paper sell quantity exceeds the open position")

    def _market_fill_price(self, side: OrderSide, ticker: Ticker) -> float:
        slip = self.slippage_bps / 10_000
        if side is OrderSide.BUY:
            return float(ticker.ask or ticker.last) * (1 + slip)
        return float(ticker.bid or ticker.last) * (1 - slip)

    @staticmethod
    def _limit_is_marketable(request: OrderRequest, ticker: Ticker) -> bool:
        assert request.price is not None
        if request.side is OrderSide.BUY:
            return request.price >= float(ticker.ask or ticker.last)
        return request.price <= float(ticker.bid or ticker.last)

    def _apply_fill(
        self, order: PaperOrder, quantity: float, price: float, request: OrderRequest
    ) -> None:
        if quantity <= 0:
            return
        quantity = min(quantity, order.remaining)
        notional = quantity * price
        fee = notional * self.fee_rate
        now = datetime.now(UTC)

        if request.side is OrderSide.BUY:
            required = notional + fee
            if required > self.cash + 1e-9:
                raise InvalidOrder(
                    f"insufficient paper balance: need {required:.8f}, have {self.cash:.8f}"
                )
            self.cash -= required
            existing = self.positions.get(request.symbol)
            if existing:
                total_quantity = existing.quantity + quantity
                existing.average_entry = (
                    existing.average_entry * existing.quantity + price * quantity
                ) / total_quantity
                existing.quantity = total_quantity
                existing.entry_fees += fee
                existing.current_price = price
                existing.stop_loss = request.stop_loss or existing.stop_loss
                existing.take_profit = request.take_profit or existing.take_profit
            else:
                self.positions[request.symbol] = PaperPosition(
                    symbol=request.symbol,
                    quantity=quantity,
                    average_entry=price,
                    entry_fees=fee,
                    opened_at=now,
                    stop_loss=request.stop_loss,
                    take_profit=request.take_profit,
                    current_price=price,
                )
        else:
            position = self.positions[request.symbol]
            old_quantity = position.quantity
            entry_fee_share = position.entry_fees * (quantity / old_quantity)
            gross_pnl = (price - position.average_entry) * quantity
            net_pnl = gross_pnl - entry_fee_share - fee
            self.cash += notional - fee
            self.realized_pnl += net_pnl
            position.realized_pnl += net_pnl
            position.quantity -= quantity
            position.entry_fees -= entry_fee_share
            if position.quantity <= 1e-12:
                del self.positions[request.symbol]

        previous_value = (order.average_fill or 0) * order.filled
        order.filled += quantity
        order.remaining = max(0.0, order.quantity - order.filled)
        order.average_fill = (previous_value + price * quantity) / order.filled
        order.fee += fee
        order.status = "closed" if order.remaining <= 1e-12 else "partially_filled"
        order.updated_at = now
        order.fills.append({"timestamp": now, "price": price, "quantity": quantity, "fee": fee})
        self.total_fees += fee

    def equity(self, prices: dict[str, float] | None = None) -> float:
        prices = prices or {}
        value = self.cash
        for symbol, position in self.positions.items():
            mark = prices.get(symbol, position.current_price or position.average_entry)
            value += position.quantity * mark
        return value

    def balances(self) -> dict[str, float]:
        balances = {self.quote_currency: self.cash}
        for symbol, position in self.positions.items():
            base, _ = split_symbol(symbol)
            balances[base] = balances.get(base, 0.0) + position.quantity
        return balances

    def restore_order(self, order: PaperOrder) -> None:
        """Restore a persisted open order during crash recovery."""
        if order.status not in {"open", "partially_filled"}:
            return
        self.orders[order.id] = order
        if order.client_order_id:
            self._client_ids[order.client_order_id] = order.id

    def reset_order_sequence(self, next_value: int) -> None:
        self._ids = itertools.count(max(1, next_value))

    def open_orders(self) -> list[PaperOrder]:
        return [
            order for order in self.orders.values() if order.status in {"open", "partially_filled"}
        ]
