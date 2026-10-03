"""Exchange-neutral contracts used by the trading engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ExchangeError(RuntimeError):
    pass


class ExchangeUnavailable(ExchangeError):
    pass


class InvalidOrder(ExchangeError):
    pass


class AmbiguousOrderError(ExchangeError):
    """Submission may have reached the exchange and must be reconciled, never retried."""


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass(frozen=True, slots=True)
class Ticker:
    symbol: str
    timestamp: datetime
    last: float
    bid: float | None = None
    ask: float | None = None
    base_volume: float | None = None
    quote_volume: float | None = None


@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    client_order_id: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    trigger_price: float | None = None


@dataclass(slots=True)
class OrderResult:
    id: str
    client_order_id: str | None
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    filled: float
    remaining: float
    price: float | None
    average: float | None
    fee: float
    timestamp: datetime
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class ExchangeClient(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def get_balance(self) -> dict[str, dict[str, float]]: ...

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker: ...

    @abstractmethod
    async def get_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 500, since: int | None = None
    ) -> list[list[float]]: ...

    @abstractmethod
    async def get_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]: ...

    @abstractmethod
    async def create_order(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> OrderResult: ...

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]: ...

    @abstractmethod
    async def get_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def find_order(
        self, *, order_id: str | None = None, client_order_id: str | None = None, symbol: str
    ) -> OrderResult | None: ...

    @abstractmethod
    def supports_websocket_ohlcv(self) -> bool: ...

    @abstractmethod
    async def watch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 250
    ) -> list[list[float]]: ...

    @abstractmethod
    def market_limits(self, symbol: str) -> dict[str, Any]: ...

    @abstractmethod
    def supports_stop_loss(self, symbol: str) -> bool: ...
