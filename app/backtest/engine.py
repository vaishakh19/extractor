"""Event-driven, next-candle execution backtester without look-ahead."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from app.backtest.metrics import calculate_metrics
from app.exchange.market_data import validate_candles
from app.strategy.base import Strategy
from app.trading.signal import SignalAction, TradingSignal


def _utc_timestamp(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    symbol: str
    timeframe: str = "5m"
    initial_capital: float = 1000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_position_percent: float = 0.25
    stop_loss_percent: float = 1.0
    take_profit_percent: float = 2.0
    start_date: str | None = None
    end_date: str | None = None

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial capital must be positive")
        if not 0 <= self.fee_rate <= 0.1 or not 0 <= self.slippage_bps <= 1000:
            raise ValueError("invalid fee or slippage")
        if not 0 < self.risk_per_trade <= 0.1:
            raise ValueError("risk per trade must be in (0, 0.1]")
        if not 0 < self.max_daily_loss <= 0.5:
            raise ValueError("maximum daily loss must be in (0, 0.5]")
        if not 0 < self.max_position_percent <= 1:
            raise ValueError("max position percentage must be in (0, 1]")
        if self.stop_loss_percent <= 0 or self.take_profit_percent <= 0:
            raise ValueError("stop loss and take profit must be positive")


@dataclass(slots=True)
class BacktestResult:
    config: BacktestConfig
    strategy: str
    metrics: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_curve: pd.DataFrame

    def serializable(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "strategy": self.strategy,
            "metrics": self.metrics,
            "trades": self.trades,
            "equity_curve": [
                {"timestamp": row["timestamp"].isoformat(), "equity": float(row["equity"])}
                for row in self.equity_curve.to_dict("records")
            ],
        }


@dataclass(slots=True)
class _Position:
    quantity: float
    entry_price: float
    entry_time: pd.Timestamp
    entry_fee: float
    stop_loss: float
    take_profit: float


class BacktestEngine:
    def __init__(self, strategy: Strategy, config: BacktestConfig) -> None:
        self.strategy = strategy
        self.config = config

    def run(self, candles: pd.DataFrame) -> BacktestResult:
        frame = validate_candles(candles)
        if self.config.start_date:
            start = _utc_timestamp(self.config.start_date)
            frame = frame[frame["timestamp"] >= start]
        if self.config.end_date:
            end = _utc_timestamp(self.config.end_date)
            frame = frame[frame["timestamp"] <= end]
        frame = frame.reset_index(drop=True)
        if len(frame) < self.strategy.warmup_period + 1:
            raise ValueError(
                f"need at least {self.strategy.warmup_period + 1} valid candles for this strategy"
            )

        cash = self.config.initial_capital
        position: _Position | None = None
        pending: TradingSignal | None = None
        trades: list[dict[str, Any]] = []
        equity_points: list[dict[str, Any]] = []
        slippage = self.config.slippage_bps / 10_000
        current_day = None
        day_start_equity = self.config.initial_capital
        daily_halted = False

        for index, candle in frame.iterrows():
            timestamp = candle["timestamp"]
            open_price = float(candle["open"])
            if current_day != timestamp.date():
                current_day = timestamp.date()
                day_start_equity = cash + (position.quantity * open_price if position else 0.0)
                daily_halted = False
            close_price = float(candle["close"])

            # A signal generated at the prior close executes at this candle's open.
            if pending is not None:
                if pending.action is SignalAction.BUY and position is None and not daily_halted:
                    fill = open_price * (1 + slippage)
                    stop = fill * (1 - self.config.stop_loss_percent / 100)
                    risk_distance = fill - stop
                    equity = cash
                    quantity_by_risk = equity * self.config.risk_per_trade / risk_distance
                    quantity_by_position = equity * self.config.max_position_percent / fill
                    quantity_by_cash = cash / (fill * (1 + self.config.fee_rate))
                    quantity = max(
                        0.0, min(quantity_by_risk, quantity_by_position, quantity_by_cash)
                    )
                    if quantity > 0:
                        notional = quantity * fill
                        entry_fee = notional * self.config.fee_rate
                        cash -= notional + entry_fee
                        position = _Position(
                            quantity=quantity,
                            entry_price=fill,
                            entry_time=timestamp,
                            entry_fee=entry_fee,
                            stop_loss=stop,
                            take_profit=fill * (1 + self.config.take_profit_percent / 100),
                        )
                elif pending.action is SignalAction.SELL and position is not None:
                    cash, trade = self._close(
                        position, open_price * (1 - slippage), timestamp, cash, "signal"
                    )
                    trades.append(trade)
                    position = None
                pending = None

            # Stops are evaluated using this candle only after its open is reached.
            if position is not None:
                exit_price: float | None = None
                reason = ""
                if float(candle["low"]) <= position.stop_loss:
                    exit_price, reason = position.stop_loss * (1 - slippage), "stop_loss"
                elif float(candle["high"]) >= position.take_profit:
                    exit_price, reason = position.take_profit * (1 - slippage), "take_profit"
                if exit_price is not None:
                    cash, trade = self._close(position, exit_price, timestamp, cash, reason)
                    trades.append(trade)
                    position = None

            equity = cash + (position.quantity * close_price if position else 0.0)
            equity_points.append({"timestamp": timestamp, "equity": equity})
            if equity <= day_start_equity * (1 - self.config.max_daily_loss):
                daily_halted = True

            # The strategy sees no future row. Its output is delayed to next open.
            history = frame.iloc[: index + 1]
            signal = self.strategy.generate_signal(history, self.config.symbol)
            if (
                signal.action is SignalAction.BUY
                and position is None
                and not daily_halted
                or signal.action is SignalAction.SELL
                and position is not None
            ):
                pending = signal

        if position is not None:
            last = frame.iloc[-1]
            exit_price = float(last["close"]) * (1 - slippage)
            cash, trade = self._close(position, exit_price, last["timestamp"], cash, "end_of_test")
            trades.append(trade)
            if equity_points:
                equity_points[-1]["equity"] = cash

        curve = pd.DataFrame(equity_points)
        metrics = calculate_metrics(self.config.initial_capital, cash, trades, curve)
        return BacktestResult(self.config, self.strategy.name, metrics, trades, curve)

    def _close(
        self,
        position: _Position,
        exit_price: float,
        exit_time: pd.Timestamp,
        cash: float,
        reason: str,
    ) -> tuple[float, dict[str, Any]]:
        proceeds = position.quantity * exit_price
        exit_fee = proceeds * self.config.fee_rate
        cash += proceeds - exit_fee
        gross_pnl = (exit_price - position.entry_price) * position.quantity
        fees = position.entry_fee + exit_fee
        net_pnl = gross_pnl - fees
        return cash, {
            "symbol": self.config.symbol,
            "side": "long",
            "entry_time": position.entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "quantity": position.quantity,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "fees": fees,
            "holding_seconds": (exit_time - position.entry_time).total_seconds(),
            "exit_reason": reason,
        }
