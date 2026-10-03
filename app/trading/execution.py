from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import TradingMode
from app.exchange.base import (
    ExchangeClient,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderType,
    Ticker,
)
from app.paper.paper_engine import PaperEngine, PaperOrder


class ExecutionHalted(RuntimeError):
    pass


class ProtectionFailure(ExecutionHalted):
    def __init__(
        self,
        message: str,
        primary: OrderResult,
        protective_stop: OrderResult | None = None,
    ) -> None:
        super().__init__(message)
        self.primary = primary
        self.protective_stop = protective_stop


@dataclass(frozen=True, slots=True)
class LiveExecutionReport:
    primary: OrderResult
    protective_stop: OrderResult | None = None


class ExecutionService(ABC):
    mode: TradingMode

    @abstractmethod
    async def execute(
        self, request: OrderRequest, ticker: Ticker
    ) -> OrderResult | PaperOrder | LiveExecutionReport: ...


class PaperExecutionService(ExecutionService):
    mode = TradingMode.PAPER

    def __init__(self, engine: PaperEngine, kill_switch: Path = Path("data/KILL_SWITCH")) -> None:
        self.engine = engine
        self.kill_switch = kill_switch

    async def execute(self, request: OrderRequest, ticker: Ticker) -> PaperOrder:
        if self.kill_switch.exists():
            raise ExecutionHalted("kill switch is active")
        return await self.engine.submit_order(request, ticker)


class LiveExecutionService(ExecutionService):
    mode = TradingMode.LIVE

    def __init__(
        self,
        client: ExchangeClient,
        *,
        live_confirmed: bool = False,
        kill_switch: Path = Path("data/KILL_SWITCH"),
    ) -> None:
        if not live_confirmed:
            raise ExecutionHalted("live execution requires explicit interactive confirmation")
        self.client = client
        self.kill_switch = kill_switch
        self.reconciled = False

    def arm_after_reconciliation(self) -> None:
        self.reconciled = True

    async def execute(self, request: OrderRequest, ticker: Ticker) -> LiveExecutionReport:
        if self.kill_switch.exists():
            raise ExecutionHalted("kill switch is active")
        if not self.reconciled:
            raise ExecutionHalted("live state has not been safely reconciled")
        if request.side is OrderSide.BUY:
            if request.stop_loss is None:
                raise ExecutionHalted("live entry rejected because it has no stop loss")
            if not self.client.supports_stop_loss(request.symbol):
                raise ExecutionHalted(
                    "exchange/market does not advertise server-side stop-loss support; live entry rejected"
                )
        primary = await self.client.create_order(request)
        protective = None
        if request.side is OrderSide.BUY:
            if primary.filled <= 0:
                self._halt_for_protection_failure()
                raise ProtectionFailure(
                    "entry order was accepted without a confirmed fill; kill switch activated for reconciliation",
                    primary,
                )
            stop_request = OrderRequest(
                symbol=request.symbol,
                side=OrderSide.SELL,
                quantity=primary.filled,
                order_type=OrderType.MARKET,
                client_order_id=f"protect-{(request.client_order_id or primary.id)[-28:]}",
                trigger_price=request.stop_loss,
            )
            try:
                protective = await self.client.create_order(stop_request)
            except Exception as exc:
                # Entry exists but no verified exchange-side protection. Persistently
                # halt all further execution; reconciliation is mandatory.
                self._halt_for_protection_failure()
                raise ProtectionFailure(
                    "entry filled but protective stop failed; kill switch activated and manual reconciliation required",
                    primary,
                ) from exc
            if (
                not protective.id
                or protective.status.lower() not in {"open", "new"}
                or primary.remaining > 1e-12
            ):
                self._halt_for_protection_failure()
                raise ProtectionFailure(
                    "entry/protective stop state is not fully confirmed; kill switch activated for reconciliation",
                    primary,
                    protective,
                )
        return LiveExecutionReport(primary, protective)

    def _halt_for_protection_failure(self) -> None:
        self.kill_switch.parent.mkdir(parents=True, exist_ok=True)
        self.kill_switch.write_text("protective stop verification failed\n", encoding="utf-8")
