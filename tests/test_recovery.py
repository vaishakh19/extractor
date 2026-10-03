from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.database.database import Database
from app.database.repositories import Repository
from app.paper.paper_engine import PaperEngine
from app.trading.recovery import RecoveryManager


def repo(tmp_path) -> Repository:
    database = Database(f"sqlite:///{tmp_path / 'recover.db'}")
    database.initialize()
    return Repository(database)


def test_restore_paper_balance(tmp_path) -> None:
    repository = repo(tmp_path)
    repository.save_balance("USDT", 750, 0, 750, 750, "paper")
    engine = PaperEngine(1000)
    result = RecoveryManager(repository).restore_paper(engine)
    assert result.safe
    assert engine.cash == 750


@pytest.mark.asyncio
async def test_unknown_live_order_requires_reconciliation(tmp_path) -> None:
    repository = repo(tmp_path)
    repository.save_order(
        {
            "exchange_order_id": None,
            "client_order_id": "sig-unknown",
            "signal_id": "unknown",
            "symbol": "BTC/USDT",
            "side": "buy",
            "order_type": "market",
            "quantity": 1,
            "filled": 0,
            "price": None,
            "average_price": None,
            "fees": 0,
            "status": "unknown",
            "mode": "live",
            "raw": {},
        }
    )
    client = AsyncMock()
    client.get_balance.return_value = {
        "total": {"BTC": 0, "USDT": 1000},
        "free": {},
        "used": {},
    }
    client.get_open_orders.return_value = []
    client.get_positions.return_value = []
    result = await RecoveryManager(repository).reconcile_live(client, ["BTC/USDT"])
    assert not result.safe
    assert "explicit reconciliation" in result.discrepancies[0]


@pytest.mark.asyncio
async def test_live_mismatch_halts(tmp_path) -> None:
    repository = repo(tmp_path)
    client = AsyncMock()
    client.get_balance.return_value = {"total": {"BTC": 1, "USDT": 1000}, "free": {}, "used": {}}
    client.get_open_orders.return_value = []
    client.get_positions.return_value = []
    result = await RecoveryManager(repository).reconcile_live(client, ["BTC/USDT"])
    assert not result.safe
    assert "quantity differs" in result.discrepancies[0]
