from __future__ import annotations

import logging
from typing import Any

from app.database.repositories import Repository
from app.exchange.base import AmbiguousOrderError, OrderRequest, OrderResult, OrderSide, Ticker
from app.paper.paper_engine import PaperEngine, PaperOrder
from app.risk.risk_manager import RiskDecision, RiskManager
from app.trading.execution import (
    ExecutionHalted,
    ExecutionService,
    LiveExecutionReport,
    LiveExecutionService,
    ProtectionFailure,
)
from app.trading.position_manager import PositionManager
from app.trading.signal import TradingSignal

logger = logging.getLogger("crypto_bot.order_manager")


class OrderManager:
    """The only signal-to-order gateway; persists idempotency state before submission."""

    def __init__(
        self,
        repository: Repository,
        risk_manager: RiskManager,
        execution: ExecutionService,
        position_manager: PositionManager,
        paper: PaperEngine | None = None,
    ) -> None:
        self.repository = repository
        self.risk = risk_manager
        self.execution = execution
        self.positions = position_manager
        self.paper = paper

    async def process_signal(
        self,
        signal: TradingSignal,
        ticker: Ticker,
        *,
        equity: float,
        available_balance: float,
        market_limits: dict[str, Any] | None = None,
    ) -> tuple[RiskDecision, OrderResult | PaperOrder | LiveExecutionReport | None]:
        if not self.repository.add_signal(signal):
            return RiskDecision(False, "duplicate signal ignored"), None
        positions = self.repository.open_positions(self.execution.mode.value)
        existing = next((p for p in positions if p["symbol"] == signal.symbol), None)
        decision = self.risk.assess(
            signal,
            equity=equity,
            available_balance=available_balance,
            open_positions=len(positions),
            existing_quantity=float(existing["quantity"]) if existing else 0.0,
            market_limits=market_limits,
        )
        self.repository.mark_signal(signal.signal_id, decision.approved, decision.reason)
        if not decision.approved or decision.order is None:
            self.repository.add_event(
                "WARNING",
                "signal_rejected",
                decision.reason,
                {"signal_id": signal.signal_id, "symbol": signal.symbol},
            )
            return decision, None

        request = decision.order
        entry_fee_share = 0.0
        if request.side is OrderSide.SELL and existing and float(existing["quantity"]) > 0:
            entry_fee_share = float(existing.get("entry_fees") or 0) * min(
                1.0, request.quantity / float(existing["quantity"])
            )
        client_id = request.client_order_id or f"sig-{signal.signal_id}"
        previous = self.repository.find_order_by_client_id(client_id)
        if previous:
            return RiskDecision(False, "duplicate order client ID ignored"), None

        self.repository.save_order(
            {
                "exchange_order_id": None,
                "client_order_id": client_id,
                "signal_id": signal.signal_id,
                "symbol": request.symbol,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "quantity": request.quantity,
                "filled": 0.0,
                "price": request.price,
                "average_price": None,
                "fees": 0.0,
                "status": "submitting",
                "mode": self.execution.mode.value,
                "raw": {},
            }
        )
        realized_before = self.paper.realized_pnl if self.paper else 0.0
        try:
            if request.side is OrderSide.SELL:
                await self._cancel_live_protection(request.symbol)
            result = await self.execution.execute(request, ticker)
        except AmbiguousOrderError:
            self.repository.save_order(
                {
                    "client_order_id": client_id,
                    "status": "unknown",
                    "exchange_order_id": None,
                    "signal_id": signal.signal_id,
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "order_type": request.order_type.value,
                    "quantity": request.quantity,
                    "filled": 0,
                    "price": request.price,
                    "average_price": None,
                    "fees": 0,
                    "mode": self.execution.mode.value,
                    "raw": {"requires_reconciliation": True},
                }
            )
            self.repository.add_event(
                "CRITICAL",
                "ambiguous_order",
                "Order outcome unknown; execution halted",
                {"client_order_id": client_id},
            )
            if isinstance(self.execution, LiveExecutionService):
                self.execution.kill_switch.parent.mkdir(parents=True, exist_ok=True)
                self.execution.kill_switch.write_text(
                    "ambiguous live order requires reconciliation\n", encoding="utf-8"
                )
            raise ExecutionHalted("ambiguous order requires manual reconciliation")
        except ProtectionFailure as exc:
            normalized = self._normalize(exc.primary)
            self.repository.save_order(
                {
                    "client_order_id": client_id,
                    "status": "unprotected",
                    "exchange_order_id": normalized["id"],
                    "signal_id": signal.signal_id,
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "order_type": request.order_type.value,
                    "quantity": request.quantity,
                    "filled": normalized["filled"],
                    "price": request.price,
                    "average_price": normalized["average"],
                    "fees": normalized["fee"],
                    "mode": self.execution.mode.value,
                    "raw": {"requires_reconciliation": True, "protection_failed": True},
                }
            )
            self.positions.apply_live_fill(
                request,
                filled=normalized["filled"],
                average_price=normalized["average"] or ticker.last,
                fee=normalized["fee"],
            )
            if exc.protective_stop:
                protective = self._normalize(exc.protective_stop)
                protective_client_id = (
                    exc.protective_stop.client_order_id or f"protect-{client_id[-28:]}"
                )
                self.repository.save_order(
                    {
                        "client_order_id": protective_client_id,
                        "exchange_order_id": protective["id"],
                        "signal_id": signal.signal_id,
                        "symbol": request.symbol,
                        "side": "sell",
                        "order_type": "stop_loss",
                        "quantity": exc.protective_stop.quantity,
                        "filled": protective["filled"],
                        "price": request.stop_loss,
                        "average_price": protective["average"],
                        "fees": protective["fee"],
                        "status": protective["status"],
                        "mode": self.execution.mode.value,
                        "raw": {
                            "protective_stop": True,
                            "reconciliation_required": True,
                        },
                    }
                )
            if normalized["filled"] > 0:
                self.repository.add_trade(
                    {
                        "order_id": normalized["id"],
                        "symbol": request.symbol,
                        "side": request.side.value,
                        "price": normalized["average"] or ticker.last,
                        "quantity": normalized["filled"],
                        "fees": normalized["fee"],
                        "strategy": signal.strategy,
                        "signal": signal.action.value,
                        "stop_loss": request.stop_loss,
                        "take_profit": request.take_profit,
                        "gross_pnl": 0,
                        "pnl": 0,
                        "mode": self.execution.mode.value,
                    }
                )
            self.repository.add_event(
                "CRITICAL",
                "protection_failed",
                str(exc),
                {"order_id": normalized["id"], "symbol": request.symbol},
            )
            raise
        except Exception as exc:
            self.repository.save_order(
                {
                    "client_order_id": client_id,
                    "status": "failed",
                    "exchange_order_id": None,
                    "signal_id": signal.signal_id,
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "order_type": request.order_type.value,
                    "quantity": request.quantity,
                    "filled": 0,
                    "price": request.price,
                    "average_price": None,
                    "fees": 0,
                    "mode": self.execution.mode.value,
                    "raw": {"error_type": type(exc).__name__},
                }
            )
            raise

        normalized = self._normalize(result)
        self.repository.save_order(
            {
                "client_order_id": client_id,
                "exchange_order_id": normalized["id"],
                "signal_id": signal.signal_id,
                "symbol": request.symbol,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "quantity": request.quantity,
                "filled": normalized["filled"],
                "price": request.price,
                "average_price": normalized["average"],
                "fees": normalized["fee"],
                "status": normalized["status"],
                "mode": self.execution.mode.value,
                "raw": normalized["raw"],
            }
        )
        if isinstance(result, LiveExecutionReport) and result.protective_stop:
            protective = self._normalize(result.protective_stop)
            protective_client_id = (
                result.protective_stop.client_order_id or f"protect-{client_id[-28:]}"
            )
            self.repository.save_order(
                {
                    "client_order_id": protective_client_id,
                    "exchange_order_id": protective["id"],
                    "signal_id": signal.signal_id,
                    "symbol": request.symbol,
                    "side": "sell",
                    "order_type": "stop_loss",
                    "quantity": result.protective_stop.quantity,
                    "filled": protective["filled"],
                    "price": request.stop_loss,
                    "average_price": protective["average"],
                    "fees": protective["fee"],
                    "status": protective["status"],
                    "mode": self.execution.mode.value,
                    "raw": {"protective_stop": True},
                }
            )
        if self.paper:
            net_pnl = self.paper.realized_pnl - realized_before
            gross_pnl = (
                net_pnl + entry_fee_share + normalized["fee"]
                if request.side is OrderSide.SELL
                else 0.0
            )
            self.positions.synchronize_paper(request.symbol)
        else:
            gross_pnl = self._live_gross_pnl(request, normalized["filled"], normalized["average"])
            net_pnl = (
                gross_pnl - entry_fee_share - normalized["fee"]
                if request.side is OrderSide.SELL
                else 0.0
            )
            self.positions.apply_live_fill(
                request,
                filled=normalized["filled"],
                average_price=normalized["average"] or ticker.last,
                fee=normalized["fee"],
                realized_pnl=net_pnl,
            )
        if normalized["filled"] > 0:
            self.repository.add_trade(
                {
                    "order_id": normalized["id"],
                    "symbol": request.symbol,
                    "side": request.side.value,
                    "price": normalized["average"] or ticker.last,
                    "quantity": normalized["filled"],
                    "fees": normalized["fee"],
                    "strategy": signal.strategy,
                    "signal": signal.action.value,
                    "stop_loss": request.stop_loss,
                    "take_profit": request.take_profit,
                    "gross_pnl": gross_pnl,
                    "pnl": net_pnl,
                    "mode": self.execution.mode.value,
                }
            )
            if net_pnl:
                self.risk.record_realized_pnl(net_pnl)
        self.repository.add_event(
            "INFO",
            "order_updated",
            f"Order {normalized['status']}",
            {
                "order_id": normalized["id"],
                "symbol": request.symbol,
                "filled": normalized["filled"],
            },
        )
        return decision, result

    async def _cancel_live_protection(self, symbol: str) -> None:
        if not isinstance(self.execution, LiveExecutionService):
            return
        for order in self.repository.list_orders(10000, open_only=True):
            if (
                order["mode"] == "live"
                and order["symbol"] == symbol
                and str(order["client_order_id"]).startswith("protect-")
                and order.get("exchange_order_id")
            ):
                cancelled = await self.execution.client.cancel_order(
                    str(order["exchange_order_id"]), symbol
                )
                self.repository.save_order(
                    {
                        "client_order_id": order["client_order_id"],
                        "exchange_order_id": cancelled.id,
                        "signal_id": order["signal_id"],
                        "symbol": symbol,
                        "side": order["side"],
                        "order_type": order["order_type"],
                        "quantity": order["quantity"],
                        "filled": cancelled.filled,
                        "price": order["price"],
                        "average_price": cancelled.average,
                        "fees": cancelled.fee,
                        "status": "cancelled",
                        "mode": "live",
                        "raw": {"protective_stop": True, "cancelled_for_exit": True},
                    }
                )

    def _live_gross_pnl(self, request: OrderRequest, filled: float, price: float | None) -> float:
        if request.side is not OrderSide.SELL or not price:
            return 0.0
        existing = next(
            (
                p
                for p in self.repository.open_positions(self.execution.mode.value)
                if p["symbol"] == request.symbol
            ),
            None,
        )
        return (price - float(existing["entry_price"])) * filled if existing else 0.0

    @staticmethod
    def _normalize(result: OrderResult | PaperOrder | LiveExecutionReport) -> dict[str, Any]:
        if isinstance(result, LiveExecutionReport):
            result = result.primary
        if isinstance(result, PaperOrder):
            return {
                "id": result.id,
                "filled": result.filled,
                "average": result.average_fill,
                "fee": result.fee,
                "status": result.status,
                "raw": {
                    "paper": True,
                    "fills": [
                        {**fill, "timestamp": fill["timestamp"].isoformat()}
                        for fill in result.fills
                    ],
                },
            }
        return {
            "id": result.id,
            "filled": result.filled,
            "average": result.average or result.price,
            "fee": result.fee,
            "status": result.status,
            "raw": {"exchange_response_stored": True},
        }
