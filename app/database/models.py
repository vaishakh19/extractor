from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.time import utc_now


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TradeModel(Base, TimestampMixin):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(128), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(10))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0)
    strategy: Mapped[str] = mapped_column(String(80), default="")
    signal: Mapped[str] = mapped_column(String(16), default="")
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0)
    pnl: Mapped[float] = mapped_column(Float, default=0)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OrderModel(Base, TimestampMixin):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Float)
    filled: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PositionModel(Base, TimestampMixin):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("symbol", "mode", name="uq_position_symbol_mode"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(10), default="long")
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    entry_fees: Mapped[float] = mapped_column(Float, default=0)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BalanceModel(Base):
    __tablename__ = "balances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    currency: Mapped[str] = mapped_column(String(20))
    free: Mapped[float] = mapped_column(Float)
    used: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    mode: Mapped[str] = mapped_column(String(16), index=True)


class SignalModel(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    strategy: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(16))
    price: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class StrategyRunModel(Base, TimestampMixin):
    __tablename__ = "strategy_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40))
    timeframe: Mapped[str] = mapped_column(String(16))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="running")
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestModel(Base):
    __tablename__ = "backtests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    symbol: Mapped[str] = mapped_column(String(40))
    timeframe: Mapped[str] = mapped_column(String(16))
    strategy: Mapped[str] = mapped_column(String(80))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class BotEventModel(Base):
    __tablename__ = "bot_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    level: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DailyStatisticModel(Base):
    __tablename__ = "daily_statistics"
    __table_args__ = (UniqueConstraint("date", "mode", name="uq_daily_date_mode"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[Any] = mapped_column(Date, index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    start_equity: Mapped[float] = mapped_column(Float)
    end_equity: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    fees: Mapped[float] = mapped_column(Float, default=0)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    trading_halted: Mapped[bool] = mapped_column(Boolean, default=False)


Index("ix_trades_symbol_executed", TradeModel.symbol, TradeModel.executed_at)
