from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exchange.base import OrderRequest, OrderResult, OrderSide, Ticker
from app.trading.execution import ExecutionHalted, LiveExecutionReport, LiveExecutionService


def result(order_id: str, side: str, filled: float, status: str = "closed") -> OrderResult:
    return OrderResult(
        id=order_id,
        client_order_id=None,
        symbol="BTC/USDT",
        side=side,
        order_type="market",
        status=status,
        quantity=filled,
        filled=filled,
        remaining=0,
        price=100,
        average=100,
        fee=0.1,
        timestamp=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_live_entry_requires_and_places_server_stop(tmp_path: Path) -> None:
    client = MagicMock()
    client.supports_stop_loss.return_value = True
    client.create_order = AsyncMock(
        side_effect=[result("entry", "buy", 1), result("stop", "sell", 0, "open")]
    )
    service = LiveExecutionService(client, live_confirmed=True, kill_switch=tmp_path / "KILL")
    service.arm_after_reconciliation()
    request = OrderRequest(
        "BTC/USDT",
        OrderSide.BUY,
        1,
        client_order_id="sig-abc",
        stop_loss=99,
        take_profit=102,
    )
    report = await service.execute(request, Ticker("BTC/USDT", datetime.now(UTC), 100))
    assert isinstance(report, LiveExecutionReport)
    assert report.protective_stop is not None
    assert client.create_order.await_count == 2
    protective_request = client.create_order.await_args_list[1].args[0]
    assert protective_request.trigger_price == 99
    assert protective_request.side is OrderSide.SELL


@pytest.mark.asyncio
async def test_live_entry_refused_without_exchange_stop_support(tmp_path: Path) -> None:
    client = MagicMock()
    client.supports_stop_loss.return_value = False
    client.create_order = AsyncMock()
    service = LiveExecutionService(client, live_confirmed=True, kill_switch=tmp_path / "KILL")
    service.arm_after_reconciliation()
    request = OrderRequest("BTC/USDT", OrderSide.BUY, 1, stop_loss=99)
    with pytest.raises(ExecutionHalted, match="server-side"):
        await service.execute(request, Ticker("BTC/USDT", datetime.now(UTC), 100))
    client.create_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfirmed_live_fill_activates_kill_switch(tmp_path: Path) -> None:
    client = MagicMock()
    client.supports_stop_loss.return_value = True
    client.create_order = AsyncMock(return_value=result("pending", "buy", 0, "open"))
    kill_switch = tmp_path / "KILL"
    service = LiveExecutionService(client, live_confirmed=True, kill_switch=kill_switch)
    service.arm_after_reconciliation()
    with pytest.raises(ExecutionHalted, match="confirmed fill"):
        await service.execute(
            OrderRequest("BTC/USDT", OrderSide.BUY, 1, stop_loss=99),
            Ticker("BTC/USDT", datetime.now(UTC), 100),
        )
    assert kill_switch.exists()


def test_live_service_cannot_be_created_silently(tmp_path: Path) -> None:
    with pytest.raises(ExecutionHalted, match="explicit"):
        LiveExecutionService(AsyncMock(), kill_switch=tmp_path / "KILL")
