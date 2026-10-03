from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(slots=True)
class DailyLossLimit:
    max_loss_fraction: float
    day: date | None = None
    start_equity: float = 0.0
    realized_pnl: float = 0.0
    halted: bool = False

    def refresh(self, equity: float, now: datetime | None = None) -> None:
        today = (now or datetime.now(UTC)).astimezone(UTC).date()
        if self.day != today:
            self.day = today
            self.start_equity = equity
            self.realized_pnl = 0.0
            self.halted = False
        elif self.start_equity <= 0:
            self.start_equity = equity

    def record(self, realized_pnl: float) -> None:
        self.realized_pnl += realized_pnl
        if (
            self.start_equity > 0
            and self.realized_pnl <= -self.start_equity * self.max_loss_fraction
        ):
            self.halted = True

    def evaluate(self, current_equity: float) -> bool:
        self.refresh(current_equity)
        if current_equity <= self.start_equity * (1 - self.max_loss_fraction):
            self.halted = True
        return not self.halted


@dataclass(frozen=True, slots=True)
class RiskLimits:
    risk_per_trade: float
    max_daily_loss: float
    max_open_positions: int
    max_position_percent: float
    stop_loss_percent: float
    take_profit_percent: float
