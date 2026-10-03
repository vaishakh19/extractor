from __future__ import annotations

from app.database.repositories import Repository
from app.exchange.base import OrderRequest, OrderSide
from app.paper.paper_engine import PaperEngine
from app.utils.time import utc_now


class PositionManager:
    def __init__(self, repository: Repository, mode: str, paper: PaperEngine | None = None) -> None:
        self.repository = repository
        self.mode = mode
        self.paper = paper

    def synchronize_paper(self, symbol: str) -> None:
        if self.paper is None:
            return
        position = self.paper.positions.get(symbol)
        if position:
            self.repository.upsert_position(
                {
                    "symbol": symbol,
                    "side": "long",
                    "quantity": position.quantity,
                    "entry_price": position.average_entry,
                    "current_price": position.current_price,
                    "unrealized_pnl": position.unrealized_pnl,
                    "realized_pnl": position.realized_pnl,
                    "entry_fees": position.entry_fees,
                    "stop_loss": position.stop_loss,
                    "take_profit": position.take_profit,
                    "mode": self.mode,
                    "is_open": True,
                    "opened_at": position.opened_at,
                    "closed_at": None,
                }
            )
        else:
            existing = next(
                (p for p in self.repository.open_positions(self.mode) if p["symbol"] == symbol),
                None,
            )
            if existing:
                existing.update(
                    {
                        "quantity": 0.0,
                        "unrealized_pnl": 0.0,
                        "is_open": False,
                        "closed_at": utc_now(),
                    }
                )
                allowed = {
                    "symbol",
                    "side",
                    "quantity",
                    "entry_price",
                    "current_price",
                    "unrealized_pnl",
                    "realized_pnl",
                    "entry_fees",
                    "stop_loss",
                    "take_profit",
                    "mode",
                    "is_open",
                    "opened_at",
                    "closed_at",
                }
                self.repository.upsert_position(
                    {key: value for key, value in existing.items() if key in allowed}
                )

    def apply_live_fill(
        self,
        request: OrderRequest,
        *,
        filled: float,
        average_price: float,
        fee: float = 0.0,
        realized_pnl: float = 0.0,
    ) -> None:
        if filled <= 0:
            return
        existing = next(
            (p for p in self.repository.open_positions(self.mode) if p["symbol"] == request.symbol),
            None,
        )
        if request.side is OrderSide.BUY:
            if existing:
                total = existing["quantity"] + filled
                entry = (
                    existing["entry_price"] * existing["quantity"] + average_price * filled
                ) / total
                opened_at = existing["opened_at"]
            else:
                total, entry, opened_at = filled, average_price, utc_now()
            self.repository.upsert_position(
                {
                    "symbol": request.symbol,
                    "side": "long",
                    "quantity": total,
                    "entry_price": entry,
                    "current_price": average_price,
                    "unrealized_pnl": 0,
                    "realized_pnl": (existing or {}).get("realized_pnl", 0),
                    "entry_fees": (existing or {}).get("entry_fees", 0) + fee,
                    "stop_loss": request.stop_loss,
                    "take_profit": request.take_profit,
                    "mode": self.mode,
                    "is_open": True,
                    "opened_at": opened_at,
                    "closed_at": None,
                }
            )
        elif existing:
            old_quantity = float(existing["quantity"])
            remaining = max(0.0, old_quantity - filled)
            allocated_entry_fee = float(existing.get("entry_fees") or 0) * min(
                1.0, filled / old_quantity
            )
            existing.update(
                {
                    "quantity": remaining,
                    "current_price": average_price,
                    "realized_pnl": existing["realized_pnl"] + realized_pnl,
                    "entry_fees": max(
                        0.0, float(existing.get("entry_fees") or 0) - allocated_entry_fee
                    ),
                    "is_open": remaining > 1e-12,
                    "closed_at": None if remaining > 1e-12 else utc_now(),
                }
            )
            allowed = {
                "symbol",
                "side",
                "quantity",
                "entry_price",
                "current_price",
                "unrealized_pnl",
                "realized_pnl",
                "entry_fees",
                "stop_loss",
                "take_profit",
                "mode",
                "is_open",
                "opened_at",
                "closed_at",
            }
            self.repository.upsert_position(
                {key: value for key, value in existing.items() if key in allowed}
            )

    def mark_prices(self, prices: dict[str, float]) -> None:
        for position in self.repository.open_positions(self.mode):
            price = prices.get(position["symbol"])
            if price is None:
                continue
            position["current_price"] = price
            position["unrealized_pnl"] = (price - position["entry_price"]) * position["quantity"]
            allowed = {
                "symbol",
                "side",
                "quantity",
                "entry_price",
                "current_price",
                "unrealized_pnl",
                "realized_pnl",
                "entry_fees",
                "stop_loss",
                "take_profit",
                "mode",
                "is_open",
                "opened_at",
                "closed_at",
            }
            self.repository.upsert_position(
                {key: value for key, value in position.items() if key in allowed}
            )
