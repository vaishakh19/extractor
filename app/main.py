"""Trading application orchestration."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.live import Live

from app.config.settings import Settings, TradingMode
from app.database.database import Database
from app.database.repositories import Repository
from app.exchange.base import Ticker
from app.exchange.ccxt_client import CCXTClient
from app.exchange.market_data import MarketDataService
from app.notifications.notifier import Notifier, NullNotifier
from app.paper.paper_engine import PaperEngine, PaperOrder
from app.risk.limits import RiskLimits
from app.risk.risk_manager import RiskManager
from app.strategy.strategy_manager import StrategyManager
from app.trading.execution import LiveExecutionService, PaperExecutionService
from app.trading.order_manager import OrderManager
from app.trading.position_manager import PositionManager
from app.trading.recovery import RecoveryManager
from app.trading.signal import SignalAction, TradingSignal
from app.utils.terminal import console, first_run_panel, status_panel

logger = logging.getLogger("crypto_bot.main")
KILL_SWITCH = Path("data/KILL_SWITCH")


class TradingBot:
    def __init__(
        self,
        settings: Settings,
        *,
        live_confirmed: bool = False,
        notifier: Notifier | None = None,
    ) -> None:
        if settings.trading_mode is TradingMode.BACKTEST:
            raise ValueError("TradingBot runs PAPER or LIVE; use BacktestEngine for backtests")
        self.settings = settings
        self.database = Database(settings.database_url)
        self.database.initialize()
        self.repository = Repository(self.database)
        self.exchange = CCXTClient(settings)
        self.market_data = MarketDataService(self.exchange, settings.poll_interval_seconds)
        self.strategy = StrategyManager().create(settings.strategy, settings)
        self.notifier = notifier or NullNotifier()
        self.stop_event = asyncio.Event()
        self._daily_initialized = False
        self.status: dict[str, Any] = {
            "price": None,
            "balance": settings.initial_paper_balance,
            "equity": settings.initial_paper_balance,
            "pnl": 0.0,
            "position": "FLAT",
            "last_signal": "waiting…",
        }

        limits = RiskLimits(
            risk_per_trade=settings.risk_per_trade,
            max_daily_loss=settings.max_daily_loss,
            max_open_positions=settings.max_open_positions,
            max_position_percent=settings.max_position_percent,
            stop_loss_percent=settings.stop_loss_percent,
            take_profit_percent=settings.take_profit_percent,
        )
        fee_rate = settings.paper_fee_rate
        self.paper: PaperEngine | None = None
        if settings.trading_mode is TradingMode.PAPER:
            self.paper = PaperEngine(
                settings.initial_paper_balance,
                quote_currency=settings.default_symbol.split("/")[1].split(":")[0],
                fee_rate=settings.paper_fee_rate,
                slippage_bps=settings.paper_slippage_bps,
                partial_fill_ratio=settings.paper_partial_fill_ratio,
            )
            execution = PaperExecutionService(self.paper, KILL_SWITCH)
        else:
            execution = LiveExecutionService(
                self.exchange, live_confirmed=live_confirmed, kill_switch=KILL_SWITCH
            )
        self.execution = execution
        self.risk = RiskManager(limits, fee_rate)
        self.position_manager = PositionManager(
            self.repository, settings.trading_mode.value, self.paper
        )
        self.order_manager = OrderManager(
            self.repository, self.risk, execution, self.position_manager, self.paper
        )
        self.recovery = RecoveryManager(self.repository)

    async def run(self) -> None:
        console.print(first_run_panel(self.settings))
        if self.settings.trading_mode is TradingMode.LIVE:
            console.print(
                "[bold red]WARNING: LIVE TRADING IS ARMED. REAL FUNDS MAY BE USED.[/bold red]"
            )
        self.repository.add_event("INFO", "startup", "Bot starting", self.settings.safe_summary())
        logger.info(
            "bot startup",
            extra={"event": "startup", "mode": self.settings.trading_mode.value},
        )
        await self.exchange.connect()
        await self._recover()
        terminal_task = asyncio.create_task(self._terminal_loop(), name="terminal-ui")
        kill_task = asyncio.create_task(self._kill_monitor(), name="kill-monitor")
        try:
            async for frame in self.market_data.stream_closed_candles(
                self.settings.default_symbol,
                self.settings.timeframe,
                self.settings.candle_limit,
            ):
                if self.stop_event.is_set() or KILL_SWITCH.exists():
                    break
                try:
                    ticker = await self.exchange.get_ticker(self.settings.default_symbol)
                    await self._cycle(frame, ticker)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("trading cycle failed; engine remains alive")
                    self.repository.add_event(
                        "ERROR",
                        "cycle_error",
                        "Trading cycle failed safely",
                        {"error_type": type(exc).__name__},
                    )
                    await self.notifier.send("Trading cycle error", type(exc).__name__)
        finally:
            self.stop_event.set()
            terminal_task.cancel()
            kill_task.cancel()
            await asyncio.gather(terminal_task, kill_task, return_exceptions=True)
            await self.exchange.close()
            self.repository.add_event("INFO", "shutdown", "Bot stopped")
            self.database.close()
            logger.info("bot shutdown", extra={"event": "shutdown"})

    async def _recover(self) -> None:
        if self.paper:
            result = self.recovery.restore_paper(self.paper)
            self.status["balance"] = self.paper.cash
            self.status["equity"] = self.paper.equity()
            return
        result = await self.recovery.reconcile_live(self.exchange, [self.settings.default_symbol])
        if not result.safe:
            await self.notifier.send("LIVE execution halted", "; ".join(result.discrepancies))
            raise RuntimeError(
                "LIVE state reconciliation failed: " + "; ".join(result.discrepancies)
            )
        assert isinstance(self.execution, LiveExecutionService)
        self.execution.arm_after_reconciliation()

    async def _cycle(self, frame, ticker: Ticker) -> None:
        self.status["price"] = ticker.last
        if self.paper:
            realized_before = self.paper.realized_pnl
            existing_paper_position = self.paper.positions.get(ticker.symbol)
            entry_fees_before = (
                existing_paper_position.entry_fees if existing_paper_position else 0.0
            )
            quantity_before = existing_paper_position.quantity if existing_paper_position else 0.0
            automatic_orders = await self.paper.process_ticker(ticker)
            for order in automatic_orders:
                await self._record_automatic_paper_order(
                    order, ticker, realized_before, entry_fees_before, quantity_before
                )
                realized_before = self.paper.realized_pnl
                entry_fees_before = 0.0
                quantity_before = 0.0
            self.position_manager.synchronize_paper(ticker.symbol)

        risk_exit = self._risk_exit_signal(ticker)
        signal = risk_exit or self.strategy.generate_signal(frame, self.settings.default_symbol)
        self.status["last_signal"] = f"{signal.action.value} · {signal.reason}"
        logger.info(
            "signal %s: %s",
            signal.action.value,
            signal.reason,
            extra={"event": "signal", "symbol": signal.symbol},
        )

        equity, available = await self._account_values(ticker)
        self._initialize_daily_limit(equity)
        market_limits = self.exchange.market_limits(ticker.symbol)
        await self.order_manager.process_signal(
            signal,
            ticker,
            equity=equity,
            available_balance=available,
            market_limits=market_limits,
        )
        equity, available = await self._account_values(ticker)
        quote = self.settings.default_symbol.split("/")[1].split(":")[0]
        self.repository.save_balance(
            quote,
            available,
            max(0.0, equity - available),
            equity,
            equity,
            self.settings.trading_mode.value,
        )
        self.position_manager.mark_prices({ticker.symbol: ticker.last})
        self._persist_daily_statistics(equity)
        positions = self.repository.open_positions(self.settings.trading_mode.value)
        self.status.update(
            {
                "balance": available,
                "equity": equity,
                "pnl": equity - self.settings.initial_paper_balance
                if self.paper
                else sum(float(p["realized_pnl"]) for p in positions),
                "position": (f"LONG {positions[0]['quantity']:.8g}" if positions else "FLAT"),
            }
        )

    def _initialize_daily_limit(self, equity: float) -> None:
        if self._daily_initialized:
            return
        row = self.repository.get_or_create_daily(self.settings.trading_mode.value, equity)
        self.risk.daily.day = row["date"]
        self.risk.daily.start_equity = float(row["start_equity"])
        self.risk.daily.realized_pnl = float(row["realized_pnl"])
        self.risk.daily.halted = bool(row["trading_halted"])
        self._daily_initialized = True

    def _persist_daily_statistics(self, equity: float) -> None:
        today = datetime.now(UTC).date()
        trades = [
            trade
            for trade in self.repository.list_trades(10000, self.settings.trading_mode.value)
            if trade["executed_at"].date() == today
        ]
        pnls = [float(trade["pnl"]) for trade in trades]
        self.repository.update_daily(
            self.settings.trading_mode.value,
            end_equity=equity,
            realized_pnl=self.risk.daily.realized_pnl,
            fees=sum(float(trade["fees"]) for trade in trades),
            trades=len(trades),
            wins=sum(value > 0 for value in pnls),
            losses=sum(value < 0 for value in pnls),
            trading_halted=self.risk.daily.halted,
        )

    def _risk_exit_signal(self, ticker: Ticker) -> TradingSignal | None:
        positions = self.repository.open_positions(self.settings.trading_mode.value)
        position = next((p for p in positions if p["symbol"] == ticker.symbol), None)
        if not position:
            return None
        reason = None
        if position["stop_loss"] and ticker.last <= position["stop_loss"]:
            reason = "stop loss reached"
        elif position["take_profit"] and ticker.last >= position["take_profit"]:
            reason = "take profit reached"
        if reason is None:
            return None
        return TradingSignal(
            SignalAction.SELL,
            ticker.symbol,
            "risk_exit",
            ticker.timestamp,
            ticker.last,
            reason,
        )

    async def _account_values(self, ticker: Ticker) -> tuple[float, float]:
        if self.paper:
            return self.paper.equity({ticker.symbol: ticker.last}), self.paper.cash
        balance = await self.exchange.get_balance()
        quote = self.settings.default_symbol.split("/")[1].split(":")[0]
        available = float(balance.get("free", {}).get(quote, 0))
        total_quote = float(balance.get("total", {}).get(quote, 0))
        position_value = sum(
            float(p["quantity"]) * ticker.last
            for p in self.repository.open_positions("live")
            if p["symbol"] == ticker.symbol
        )
        return total_quote + position_value, available

    async def _record_automatic_paper_order(
        self,
        order: PaperOrder,
        ticker: Ticker,
        realized_before: float,
        entry_fees_before: float,
        quantity_before: float,
    ) -> None:
        if order.filled <= 0:
            return
        realized = self.paper.realized_pnl - realized_before if self.paper else 0.0
        allocated_entry_fee = (
            entry_fees_before * min(1.0, order.filled / quantity_before)
            if quantity_before > 0 and order.side == "sell"
            else 0.0
        )
        self.repository.save_order(
            {
                "exchange_order_id": order.id,
                "client_order_id": order.client_order_id or order.id,
                "signal_id": None,
                "symbol": order.symbol,
                "side": order.side,
                "order_type": order.order_type,
                "quantity": order.quantity,
                "filled": order.filled,
                "price": order.requested_price,
                "average_price": order.average_fill,
                "fees": order.fee,
                "status": order.status,
                "mode": "paper",
                "raw": {"automatic": True},
            }
        )
        self.position_manager.synchronize_paper(order.symbol)
        self.repository.add_trade(
            {
                "order_id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "price": order.average_fill or ticker.last,
                "quantity": order.filled,
                "fees": order.fee,
                "strategy": "risk_exit",
                "signal": "SELL",
                "stop_loss": None,
                "take_profit": None,
                "gross_pnl": (
                    realized + allocated_entry_fee + order.fee if order.side == "sell" else 0.0
                ),
                "pnl": realized,
                "mode": "paper",
            }
        )
        self.risk.record_realized_pnl(realized)

    async def _terminal_loop(self) -> None:
        with Live(
            status_panel(self.settings, self.status),
            console=console,
            refresh_per_second=2,
            transient=False,
        ) as live:
            while not self.stop_event.is_set():
                live.update(status_panel(self.settings, self.status))
                await asyncio.sleep(0.5)

    async def _kill_monitor(self) -> None:
        while not self.stop_event.is_set():
            if KILL_SWITCH.exists():
                logger.critical("kill switch activated", extra={"event": "kill_switch"})
                self.repository.add_event(
                    "CRITICAL", "kill_switch", "Kill switch activated; no new orders allowed"
                )
                self.stop_event.set()
                return
            await asyncio.sleep(0.25)

    def stop(self) -> None:
        self.stop_event.set()
