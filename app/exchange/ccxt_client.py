"""Async CCXT exchange adapter.

Read-only operations may be retried. Order submission is deliberately attempted once:
a timeout after submission is ambiguous and must be reconciled by client order ID.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import ccxt.async_support as ccxt

try:
    import ccxt.pro as ccxt_pro
except ImportError:  # pragma: no cover - older/minimal CCXT installations
    ccxt_pro = None

from app.config.settings import Settings
from app.exchange.base import (
    AmbiguousOrderError,
    ExchangeClient,
    ExchangeError,
    ExchangeUnavailable,
    InvalidOrder,
    OrderRequest,
    OrderResult,
    Ticker,
)
from app.utils.helpers import positive_decimal, validate_symbol

T = TypeVar("T")
logger = logging.getLogger("crypto_bot.exchange.ccxt")


class CircuitBreaker:
    def __init__(self, threshold: int = 5, reset_seconds: float = 30.0) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if time.monotonic() - self.opened_at >= self.reset_seconds:
            self.failures = 0
            self.opened_at = None
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class CCXTClient(ExchangeClient):
    def __init__(self, settings: Settings, exchange: Any | None = None) -> None:
        self.settings = settings
        self._markets_loaded = False
        self._breaker = CircuitBreaker()
        if exchange is not None:
            self.exchange = exchange
            return
        # CCXT Pro ships with current CCXT distributions and provides WebSocket
        # methods. Fall back to the async REST adapter when it is unavailable.
        exchange_class = (
            getattr(ccxt_pro, settings.exchange, None) if ccxt_pro is not None else None
        ) or getattr(ccxt, settings.exchange, None)
        if exchange_class is None:
            raise ValueError(f"CCXT does not support exchange {settings.exchange!r}")
        options: dict[str, Any] = {
            "enableRateLimit": True,
            "timeout": int(settings.request_timeout_seconds * 1000),
            "options": {"adjustForTimeDifference": True},
        }
        key = settings.api_key.get_secret_value()
        secret = settings.api_secret.get_secret_value()
        password = settings.api_password.get_secret_value()
        if key:
            options["apiKey"] = key
        if secret:
            options["secret"] = secret
        if password:
            options["password"] = password
        self.exchange = exchange_class(options)

    async def _read_retry(self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        if not self._breaker.allow():
            raise ExchangeUnavailable("exchange circuit breaker is open")
        attempts = self.settings.max_retries + 1
        for attempt in range(attempts):
            try:
                result = await call()
                self._breaker.success()
                return result
            except (ccxt.AuthenticationError, ccxt.PermissionDenied, ccxt.BadSymbol) as exc:
                raise ExchangeError(f"{operation} rejected: {type(exc).__name__}") from exc
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
                self._breaker.failure()
                if attempt >= attempts - 1:
                    raise ExchangeUnavailable(
                        f"{operation} failed after {attempts} attempts"
                    ) from exc
                delay = min(30.0, 0.5 * (2**attempt)) + random.uniform(0, 0.25)
                logger.warning("%s failed; retrying in %.2fs", operation, delay)
                await asyncio.sleep(delay)
            except ccxt.BaseError as exc:
                raise ExchangeError(f"{operation} failed: {type(exc).__name__}") from exc
        raise ExchangeUnavailable(f"{operation} failed")

    async def connect(self) -> None:
        await self._read_retry("load_markets", self.exchange.load_markets)
        self._markets_loaded = True
        logger.info("exchange connected", extra={"event": "exchange_connected"})

    async def close(self) -> None:
        close = getattr(self.exchange, "close", None)
        if close:
            await close()

    async def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            await self.connect()

    async def get_balance(self) -> dict[str, dict[str, float]]:
        result = await self._read_retry("fetch_balance", self.exchange.fetch_balance)
        return {
            "free": {key: float(value or 0) for key, value in result.get("free", {}).items()},
            "used": {key: float(value or 0) for key, value in result.get("used", {}).items()},
            "total": {key: float(value or 0) for key, value in result.get("total", {}).items()},
        }

    async def get_ticker(self, symbol: str) -> Ticker:
        symbol = validate_symbol(symbol)
        raw = await self._read_retry("fetch_ticker", lambda: self.exchange.fetch_ticker(symbol))
        last = raw.get("last") or raw.get("close")
        if last is None or float(last) <= 0:
            raise ExchangeError("exchange returned a ticker without a valid last price")
        timestamp = raw.get("timestamp")
        at = datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp else datetime.now(UTC)
        return Ticker(
            symbol=symbol,
            timestamp=at,
            last=float(last),
            bid=float(raw["bid"]) if raw.get("bid") is not None else None,
            ask=float(raw["ask"]) if raw.get("ask") is not None else None,
            base_volume=float(raw["baseVolume"]) if raw.get("baseVolume") is not None else None,
            quote_volume=float(raw["quoteVolume"]) if raw.get("quoteVolume") is not None else None,
        )

    async def get_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 500, since: int | None = None
    ) -> list[list[float]]:
        symbol = validate_symbol(symbol)
        if limit < 1 or limit > 5000:
            raise ValueError("OHLCV limit must be between 1 and 5000")
        data = await self._read_retry(
            "fetch_ohlcv",
            lambda: self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=since, limit=limit
            ),
        )
        return [list(map(float, candle[:6])) for candle in data]

    async def get_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        symbol = validate_symbol(symbol)
        if limit < 1 or limit > 1000:
            raise ValueError("order book limit must be between 1 and 1000")
        return await self._read_retry(
            "fetch_order_book", lambda: self.exchange.fetch_order_book(symbol, limit)
        )

    async def create_order(self, request: OrderRequest) -> OrderResult:
        await self._ensure_markets()
        self._validate_order(request)
        params: dict[str, Any] = {}
        if request.client_order_id:
            params["clientOrderId"] = request.client_order_id
        if request.trigger_price is not None:
            positive_decimal(request.trigger_price, "trigger_price")
            params["stopLossPrice"] = request.trigger_price
        try:
            raw = await self.exchange.create_order(
                request.symbol,
                request.order_type.value,
                request.side.value,
                request.quantity,
                request.price,
                params,
            )
        except (ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            raise AmbiguousOrderError(
                "order outcome is unknown; reconcile by client order ID before any new submission"
            ) from exc
        except (ccxt.InvalidOrder, ccxt.InsufficientFunds, ccxt.BadRequest) as exc:
            raise InvalidOrder(f"exchange rejected order: {type(exc).__name__}") from exc
        except ccxt.BaseError as exc:
            raise ExchangeError(f"order submission failed: {type(exc).__name__}") from exc
        return self._order_result(raw, request.symbol)

    def _validate_order(self, request: OrderRequest) -> None:
        validate_symbol(request.symbol)
        positive_decimal(request.quantity, "quantity")
        if request.order_type.value == "limit":
            if request.price is None:
                raise InvalidOrder("limit order requires a price")
            positive_decimal(request.price, "price")
        market = getattr(self.exchange, "markets", {}).get(request.symbol, {})
        limits = market.get("limits", {})
        amount_min = (limits.get("amount") or {}).get("min")
        cost_min = (limits.get("cost") or {}).get("min")
        if amount_min is not None and request.quantity < float(amount_min):
            raise InvalidOrder(f"quantity is below exchange minimum {amount_min}")
        reference_price = request.price
        if (
            cost_min is not None
            and reference_price
            and request.quantity * reference_price < float(cost_min)
        ):
            raise InvalidOrder(f"order notional is below exchange minimum {cost_min}")

    async def cancel_order(self, order_id: str, symbol: str) -> OrderResult:
        try:
            raw = await self.exchange.cancel_order(order_id, validate_symbol(symbol))
        except ccxt.BaseError as exc:
            raise ExchangeError(f"cancel failed: {type(exc).__name__}") from exc
        return self._order_result(raw, symbol)

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        if symbol:
            symbol = validate_symbol(symbol)
        raw = await self._read_retry(
            "fetch_open_orders", lambda: self.exchange.fetch_open_orders(symbol)
        )
        return [self._order_result(item, symbol or item.get("symbol", "")) for item in raw]

    async def get_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if not getattr(self.exchange, "has", {}).get("fetchPositions"):
            return []
        validated = [validate_symbol(value) for value in symbols] if symbols else None
        return await self._read_retry(
            "fetch_positions", lambda: self.exchange.fetch_positions(validated)
        )

    async def find_order(
        self, *, order_id: str | None = None, client_order_id: str | None = None, symbol: str
    ) -> OrderResult | None:
        symbol = validate_symbol(symbol)
        try:
            if order_id and getattr(self.exchange, "has", {}).get("fetchOrder"):
                raw = await self._read_retry(
                    "fetch_order", lambda: self.exchange.fetch_order(order_id, symbol)
                )
                return self._order_result(raw, symbol)
            orders = await self.get_open_orders(symbol)
            for order in orders:
                if client_order_id and order.client_order_id == client_order_id:
                    return order
        except ExchangeError:
            return None
        return None

    def supports_websocket_ohlcv(self) -> bool:
        return bool(
            getattr(self.exchange, "has", {}).get("watchOHLCV")
            and hasattr(self.exchange, "watch_ohlcv")
        )

    async def watch_ohlcv(self, symbol: str, timeframe: str, limit: int = 250) -> list[list[float]]:
        if not self.supports_websocket_ohlcv():
            raise ExchangeUnavailable("exchange does not provide OHLCV WebSocket streaming")
        try:
            data = await self.exchange.watch_ohlcv(
                validate_symbol(symbol), timeframe=timeframe, limit=limit
            )
            self._breaker.success()
            return [list(map(float, candle[:6])) for candle in data]
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            self._breaker.failure()
            raise ExchangeUnavailable("WebSocket OHLCV stream disconnected") from exc
        except ccxt.BaseError as exc:
            raise ExchangeError(f"WebSocket OHLCV failed: {type(exc).__name__}") from exc

    def market_limits(self, symbol: str) -> dict[str, Any]:
        market = getattr(self.exchange, "markets", {}).get(validate_symbol(symbol), {})
        return dict(market.get("limits", {}))

    def supports_stop_loss(self, symbol: str) -> bool:
        """Check CCXT's per-market feature map before any live entry is submitted."""
        feature_value = getattr(self.exchange, "feature_value", None)
        if feature_value is None:
            feature_value = getattr(self.exchange, "featureValue", None)
        if feature_value:
            try:
                return bool(feature_value(validate_symbol(symbol), "createOrder", "stopLossPrice"))
            except Exception:  # noqa: BLE001 - feature probing must fail closed
                return False
        return False

    @staticmethod
    def _order_result(raw: dict[str, Any], symbol: str) -> OrderResult:
        fee = raw.get("fee") or {}
        timestamp = raw.get("timestamp")
        return OrderResult(
            id=str(raw.get("id", "")),
            client_order_id=raw.get("clientOrderId") or raw.get("clientOrderID"),
            symbol=raw.get("symbol") or symbol,
            side=str(raw.get("side", "")),
            order_type=str(raw.get("type", "")),
            status=str(raw.get("status", "unknown")),
            quantity=float(raw.get("amount") or 0),
            filled=float(raw.get("filled") or 0),
            remaining=float(raw.get("remaining") or 0),
            price=float(raw["price"]) if raw.get("price") is not None else None,
            average=float(raw["average"]) if raw.get("average") is not None else None,
            fee=float(fee.get("cost") or 0),
            timestamp=(
                datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp else datetime.now(UTC)
            ),
            raw=raw,
        )
