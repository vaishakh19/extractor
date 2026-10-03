from __future__ import annotations

from datetime import UTC, datetime

from app.database.database import Database
from app.database.repositories import Repository


def repository(tmp_path) -> Repository:
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.initialize()
    return Repository(db)


def test_trade_insertion_and_retrieval(tmp_path) -> None:
    repo = repository(tmp_path)
    repo.add_trade(
        {
            "order_id": "order-1",
            "symbol": "BTC/USDT",
            "side": "buy",
            "price": 100.0,
            "quantity": 1.0,
            "fees": 0.1,
            "strategy": "test",
            "signal": "BUY",
            "stop_loss": 99,
            "take_profit": 102,
            "gross_pnl": 0,
            "pnl": 0,
            "mode": "paper",
        }
    )
    trades = repo.list_trades(mode="paper")
    assert len(trades) == 1
    assert trades[0]["order_id"] == "order-1"


def test_position_state_upsert(tmp_path) -> None:
    repo = repository(tmp_path)
    values = {
        "symbol": "BTC/USDT",
        "side": "long",
        "quantity": 1,
        "entry_price": 100,
        "current_price": 105,
        "unrealized_pnl": 5,
        "realized_pnl": 0,
        "stop_loss": 99,
        "take_profit": 110,
        "mode": "paper",
        "is_open": True,
        "opened_at": datetime.now(UTC),
        "closed_at": None,
    }
    repo.upsert_position(values)
    values.update({"quantity": 2, "unrealized_pnl": 10})
    repo.upsert_position(values)
    positions = repo.open_positions("paper")
    assert len(positions) == 1
    assert positions[0]["quantity"] == 2


def test_order_upsert_is_idempotent(tmp_path) -> None:
    repo = repository(tmp_path)
    values = {
        "exchange_order_id": None,
        "client_order_id": "cid",
        "signal_id": "sig",
        "symbol": "BTC/USDT",
        "side": "buy",
        "order_type": "market",
        "quantity": 1,
        "filled": 0,
        "price": None,
        "average_price": None,
        "fees": 0,
        "status": "submitting",
        "mode": "paper",
        "raw": {},
    }
    repo.save_order(values)
    values.update({"status": "closed", "filled": 1})
    repo.save_order(values)
    assert len(repo.list_orders()) == 1
    assert repo.list_orders()[0]["status"] == "closed"
