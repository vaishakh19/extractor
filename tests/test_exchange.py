from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.exchange.base import InvalidOrder, OrderRequest, OrderSide, OrderType
from app.exchange.ccxt_client import CCXTClient


class FakeExchange:
    def __init__(self) -> None:
        self.markets = {"BTC/USDT": {"limits": {"amount": {"min": 0.001}, "cost": {"min": 10}}}}
        self.has = {"fetchPositions": False}
        self.load_markets = AsyncMock(return_value=self.markets)
        self.fetch_ticker = AsyncMock(
            return_value={
                "symbol": "BTC/USDT",
                "timestamp": 1_700_000_000_000,
                "last": 100.0,
                "bid": 99,
                "ask": 101,
            }
        )
        self.fetch_ohlcv = AsyncMock(return_value=[[1_700_000_000_000, 99, 101, 98, 100, 2]])
        self.fetch_order_book = AsyncMock(return_value={"bids": [[99, 1]], "asks": [[101, 1]]})
        self.fetch_balance = AsyncMock(
            return_value={"free": {"USDT": 10}, "used": {}, "total": {"USDT": 10}}
        )
        self.create_order = AsyncMock(
            return_value={
                "id": "abc",
                "clientOrderId": "cid",
                "symbol": "BTC/USDT",
                "side": "buy",
                "type": "limit",
                "status": "open",
                "amount": 0.2,
                "filled": 0,
                "remaining": 0.2,
                "price": 100,
                "timestamp": 1_700_000_000_000,
            }
        )
        self.close = AsyncMock()


@pytest.mark.asyncio
async def test_ccxt_market_data_mapping() -> None:
    fake = FakeExchange()
    client = CCXTClient(Settings(_env_file=None, max_retries=0), fake)
    await client.connect()
    ticker = await client.get_ticker("BTC/USDT")
    candles = await client.get_ohlcv("BTC/USDT", "5m", 10)
    assert ticker.last == 100
    assert ticker.ask == 101
    assert candles[0][-1] == 2


@pytest.mark.asyncio
async def test_ccxt_validates_order_minimums() -> None:
    fake = FakeExchange()
    client = CCXTClient(Settings(_env_file=None), fake)
    client._markets_loaded = True
    with pytest.raises(InvalidOrder, match="below exchange minimum"):
        await client.create_order(
            OrderRequest("BTC/USDT", OrderSide.BUY, 0.0001, OrderType.LIMIT, 100)
        )
    fake.create_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_ccxt_submits_order_once() -> None:
    fake = FakeExchange()
    client = CCXTClient(Settings(_env_file=None), fake)
    client._markets_loaded = True
    result = await client.create_order(
        OrderRequest("BTC/USDT", OrderSide.BUY, 0.2, OrderType.LIMIT, 100, "cid")
    )
    assert result.id == "abc"
    fake.create_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_ccxt_never_retries_ambiguous_order_submission() -> None:
    import ccxt.async_support as ccxt

    from app.exchange.base import AmbiguousOrderError

    fake = FakeExchange()
    fake.create_order.side_effect = ccxt.RequestTimeout("uncertain")
    client = CCXTClient(Settings(_env_file=None, max_retries=5), fake)
    client._markets_loaded = True
    with pytest.raises(AmbiguousOrderError):
        await client.create_order(
            OrderRequest("BTC/USDT", OrderSide.BUY, 0.2, OrderType.LIMIT, 100, "cid")
        )
    fake.create_order.assert_awaited_once()
