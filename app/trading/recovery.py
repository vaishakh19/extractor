"""Restart reconciliation. Any discrepancy prevents live execution from arming."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.database.repositories import Repository
from app.exchange.base import ExchangeClient
from app.paper.paper_engine import PaperEngine, PaperOrder, PaperPosition
from app.utils.helpers import split_symbol

logger = logging.getLogger("crypto_bot.recovery")


@dataclass(slots=True)
class RecoveryResult:
    safe: bool
    discrepancies: list[str] = field(default_factory=list)


class RecoveryManager:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def restore_paper(self, engine: PaperEngine) -> RecoveryResult:
        balance = self.repository.latest_balance("paper")
        if balance:
            engine.cash = float(balance["free"])
        for row in self.repository.open_positions("paper"):
            engine.positions[row["symbol"]] = PaperPosition(
                symbol=row["symbol"],
                quantity=float(row["quantity"]),
                average_entry=float(row["entry_price"]),
                entry_fees=float(row.get("entry_fees") or 0),
                opened_at=row["opened_at"],
                stop_loss=row["stop_loss"],
                take_profit=row["take_profit"],
                current_price=float(row["current_price"]),
                realized_pnl=float(row["realized_pnl"]),
            )
        maximum_sequence = 0
        for row in self.repository.list_orders(10000):
            order_id = str(row.get("exchange_order_id") or "")
            if order_id.startswith("paper-"):
                try:
                    maximum_sequence = max(maximum_sequence, int(order_id.rsplit("-", 1)[1]))
                except ValueError:
                    pass
            if row["mode"] == "paper" and row["status"] in {"open", "partially_filled"}:
                engine.restore_order(
                    PaperOrder(
                        id=order_id or str(row["client_order_id"]),
                        symbol=row["symbol"],
                        side=row["side"],
                        order_type=row["order_type"],
                        quantity=float(row["quantity"]),
                        filled=float(row["filled"]),
                        remaining=max(0.0, float(row["quantity"]) - float(row["filled"])),
                        status=row["status"],
                        requested_price=row["price"],
                        average_fill=row["average_price"],
                        fee=float(row["fees"]),
                        client_order_id=row["client_order_id"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        fills=[],
                    )
                )
        engine.reset_order_sequence(maximum_sequence + 1)
        trades = self.repository.list_trades(10000, "paper")
        engine.realized_pnl = sum(float(trade["pnl"]) for trade in trades)
        engine.total_fees = sum(float(trade["fees"]) for trade in trades)
        self.repository.add_event(
            "INFO",
            "paper_recovered",
            "Paper account restored from local state",
            {
                "positions": len(engine.positions),
                "orders": len(engine.open_orders()),
                "cash": engine.cash,
            },
        )
        return RecoveryResult(True)

    async def reconcile_live(
        self, client: ExchangeClient, symbols: list[str], tolerance: float = 1e-8
    ) -> RecoveryResult:
        discrepancies: list[str] = []
        local_positions = {p["symbol"]: p for p in self.repository.open_positions("live")}
        local_orders = self.repository.list_orders(10000, open_only=True)
        try:
            balances = await client.get_balance()
            exchange_orders = []
            for symbol in symbols:
                exchange_orders.extend(await client.get_open_orders(symbol))
            exchange_positions = await client.get_positions(symbols)
        except Exception as exc:  # noqa: BLE001 - any failed query must disarm live execution
            message = f"exchange state query failed: {type(exc).__name__}"
            self.repository.add_event("CRITICAL", "reconciliation_failed", message)
            return RecoveryResult(False, [message])

        uncertain = [
            str(order["client_order_id"])
            for order in local_orders
            if order["status"] in {"unknown", "submitting", "unprotected"}
        ]
        if uncertain:
            discrepancies.append(
                "local orders require explicit reconciliation: " + ", ".join(sorted(uncertain))
            )

        exchange_ids = {order.id for order in exchange_orders}
        local_exchange_ids = {
            str(order["exchange_order_id"])
            for order in local_orders
            if order.get("exchange_order_id")
        }
        if exchange_ids != local_exchange_ids:
            discrepancies.append(
                f"open order IDs differ (local={sorted(local_exchange_ids)}, exchange={sorted(exchange_ids)})"
            )

        if exchange_positions:
            remote_quantities: dict[str, float] = {}
            for position in exchange_positions:
                symbol = position.get("symbol")
                contracts = float(position.get("contracts") or 0)
                if symbol and abs(contracts) > tolerance:
                    remote_quantities[symbol] = contracts
        else:
            # Spot exchanges commonly have no positions endpoint; compare base total balance.
            remote_quantities = {}
            totals = balances.get("total", {})
            for symbol in symbols:
                base, _ = split_symbol(symbol)
                quantity = float(totals.get(base, 0) or 0)
                if quantity > tolerance:
                    remote_quantities[symbol] = quantity

        for symbol in set(local_positions) | set(remote_quantities):
            local_qty = float(local_positions.get(symbol, {}).get("quantity", 0))
            remote_qty = float(remote_quantities.get(symbol, 0))
            if abs(local_qty - remote_qty) > tolerance * max(1.0, abs(remote_qty)):
                discrepancies.append(
                    f"{symbol} quantity differs (local={local_qty:.12g}, exchange={remote_qty:.12g})"
                )

        safe = not discrepancies
        level = "INFO" if safe else "CRITICAL"
        message = (
            "Live state reconciled" if safe else "Live state mismatch; execution remains halted"
        )
        self.repository.add_event(
            level, "reconciliation", message, {"discrepancies": discrepancies}
        )
        if discrepancies:
            logger.critical("%s: %s", message, "; ".join(discrepancies))
        return RecoveryResult(safe, discrepancies)
