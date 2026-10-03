from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.exchange.base import InvalidOrder, OrderRequest, OrderSide, OrderType, Ticker
from app.paper.paper_engine import PaperEngine


def ticker(price: float, *, bid: float | None = None, ask: float | None = None) -> Ticker:
    return Ticker("BTC/USDT", datetime.now(UTC), price, bid=bid, ask=ask)


@pytest.mark.asyncio
async def test_paper_buy_sell_fees_and_pnl() -> None:
    engine = PaperEngine(1000, fee_rate=0.001, slippage_bps=0)
    buy = await engine.submit_order(OrderRequest("BTC/USDT", OrderSide.BUY, 1), ticker(100))
    assert buy.status == "closed"
    assert engine.cash == pytest.approx(899.9)
    assert engine.positions["BTC/USDT"].quantity == 1

    sell = await engine.submit_order(OrderRequest("BTC/USDT", OrderSide.SELL, 1), ticker(110))
    assert sell.status == "closed"
    assert "BTC/USDT" not in engine.positions
    assert engine.cash == pytest.approx(1009.79)
    assert engine.realized_pnl == pytest.approx(9.79)
    assert engine.total_fees == pytest.approx(0.21)


@pytest.mark.asyncio
async def test_paper_rejects_overspend_and_oversell() -> None:
    engine = PaperEngine(100)
    with pytest.raises(InvalidOrder, match="insufficient"):
        await engine.submit_order(OrderRequest("BTC/USDT", OrderSide.BUY, 2), ticker(100))
    with pytest.raises(InvalidOrder, match="exceeds"):
        await engine.submit_order(OrderRequest("BTC/USDT", OrderSide.SELL, 1), ticker(100))


@pytest.mark.asyncio
async def test_limit_partial_fills() -> None:
    engine = PaperEngine(1000, fee_rate=0, partial_fill_ratio=0.5)
    order = await engine.submit_order(
        OrderRequest("BTC/USDT", OrderSide.BUY, 2, OrderType.LIMIT, 99), ticker(100)
    )
    assert order.status == "open"
    await engine.process_ticker(ticker(98))
    assert order.status == "partially_filled"
    assert order.filled == 1
    await engine.process_ticker(ticker(98))
    assert order.status == "closed"
    assert order.filled == 2
