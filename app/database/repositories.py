from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from typing import Any, TypeVar

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from app.database.database import Database
from app.database.models import (
    BacktestModel,
    BalanceModel,
    BotEventModel,
    DailyStatisticModel,
    OrderModel,
    PositionModel,
    SignalModel,
    TradeModel,
)
from app.trading.signal import TradingSignal

ModelT = TypeVar("ModelT")


def model_dict(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf"
    return value


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_event(
        self, level: str, event_type: str, message: str, details: dict[str, Any] | None = None
    ) -> BotEventModel:
        with self.database.session() as session:
            event = BotEventModel(
                level=level.upper(),
                event_type=event_type,
                message=message,
                details=_json_safe(details or {}),
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            return event

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(
                select(BotEventModel).order_by(desc(BotEventModel.timestamp)).limit(limit)
            ).all()
            return [model_dict(row) for row in rows]

    def add_signal(self, signal: TradingSignal) -> bool:
        with self.database.session() as session:
            session.add(
                SignalModel(
                    signal_id=signal.signal_id,
                    timestamp=signal.timestamp,
                    symbol=signal.symbol,
                    strategy=signal.strategy,
                    action=signal.action.value,
                    price=signal.price,
                    reason=signal.reason,
                    metadata_json=_json_safe(signal.metadata),
                )
            )
            try:
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def mark_signal(self, signal_id: str, approved: bool, reason: str = "") -> None:
        with self.database.session() as session:
            signal = session.scalar(select(SignalModel).where(SignalModel.signal_id == signal_id))
            if signal:
                signal.approved = approved
                signal.rejection_reason = None if approved else reason
                session.commit()

    def signal_exists(self, signal_id: str) -> bool:
        with self.database.session() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(SignalModel)
                    .where(SignalModel.signal_id == signal_id)
                )
                > 0
            )

    def save_order(self, values: dict[str, Any]) -> OrderModel:
        client_id = str(values["client_order_id"])
        with self.database.session() as session:
            order = session.scalar(
                select(OrderModel).where(OrderModel.client_order_id == client_id)
            )
            if order is None:
                order = OrderModel(
                    client_order_id=client_id,
                    **{
                        key: _json_safe(value)
                        for key, value in values.items()
                        if key != "client_order_id"
                    },
                )
                session.add(order)
            else:
                for key, value in values.items():
                    if key != "client_order_id" and hasattr(order, key):
                        setattr(order, key, _json_safe(value))
            session.commit()
            session.refresh(order)
            return order

    def find_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.scalar(
                select(OrderModel).where(OrderModel.client_order_id == client_order_id)
            )
            return model_dict(row) if row else None

    def list_orders(self, limit: int = 100, open_only: bool = False) -> list[dict[str, Any]]:
        with self.database.session() as session:
            query = select(OrderModel)
            if open_only:
                query = query.where(
                    OrderModel.status.in_(
                        ["open", "partially_filled", "unknown", "submitting", "unprotected"]
                    )
                )
            rows = session.scalars(query.order_by(desc(OrderModel.created_at)).limit(limit)).all()
            return [model_dict(row) for row in rows]

    def add_trade(self, values: dict[str, Any]) -> TradeModel:
        with self.database.session() as session:
            trade = TradeModel(**values)
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade

    def list_trades(self, limit: int = 100, mode: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            query = select(TradeModel)
            if mode:
                query = query.where(TradeModel.mode == mode)
            rows = session.scalars(query.order_by(desc(TradeModel.executed_at)).limit(limit)).all()
            return [model_dict(row) for row in rows]

    def upsert_position(self, values: dict[str, Any]) -> PositionModel:
        symbol, mode = str(values["symbol"]), str(values["mode"])
        with self.database.session() as session:
            position = session.scalar(
                select(PositionModel).where(
                    PositionModel.symbol == symbol, PositionModel.mode == mode
                )
            )
            if position is None:
                position = PositionModel(**values)
                session.add(position)
            else:
                for key, value in values.items():
                    setattr(position, key, value)
            session.commit()
            session.refresh(position)
            return position

    def open_positions(self, mode: str | None = None) -> list[dict[str, Any]]:
        with self.database.session() as session:
            query = select(PositionModel).where(PositionModel.is_open.is_(True))
            if mode:
                query = query.where(PositionModel.mode == mode)
            rows = session.scalars(query.order_by(PositionModel.symbol)).all()
            return [model_dict(row) for row in rows]

    def save_balance(
        self, currency: str, free: float, used: float, total: float, equity: float, mode: str
    ) -> BalanceModel:
        with self.database.session() as session:
            balance = BalanceModel(
                currency=currency, free=free, used=used, total=total, equity=equity, mode=mode
            )
            session.add(balance)
            session.commit()
            session.refresh(balance)
            return balance

    def latest_balance(self, mode: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            row = session.scalar(
                select(BalanceModel)
                .where(BalanceModel.mode == mode)
                .order_by(desc(BalanceModel.timestamp))
                .limit(1)
            )
            return model_dict(row) if row else None

    def save_backtest(
        self,
        symbol: str,
        timeframe: str,
        strategy: str,
        parameters: dict[str, Any],
        metrics: dict[str, Any],
        report_path: str | None = None,
    ) -> BacktestModel:
        with self.database.session() as session:
            row = BacktestModel(
                symbol=symbol,
                timeframe=timeframe,
                strategy=strategy,
                parameters=_json_safe(parameters),
                metrics=_json_safe(metrics),
                report_path=report_path,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_backtests(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(
                select(BacktestModel).order_by(desc(BacktestModel.created_at)).limit(limit)
            ).all()
            return [model_dict(row) for row in rows]

    def get_or_create_daily(
        self, mode: str, equity: float, day: date | None = None
    ) -> dict[str, Any]:
        day = day or datetime.now(UTC).date()
        with self.database.session() as session:
            row = session.scalar(
                select(DailyStatisticModel).where(
                    DailyStatisticModel.date == day, DailyStatisticModel.mode == mode
                )
            )
            if row is None:
                row = DailyStatisticModel(
                    date=day, mode=mode, start_equity=equity, end_equity=equity
                )
                session.add(row)
                session.commit()
                session.refresh(row)
            return model_dict(row)

    def update_daily(self, mode: str, **values: Any) -> None:
        day = datetime.now(UTC).date()
        with self.database.session() as session:
            row = session.scalar(
                select(DailyStatisticModel).where(
                    DailyStatisticModel.date == day, DailyStatisticModel.mode == mode
                )
            )
            if row:
                for key, value in values.items():
                    if hasattr(row, key):
                        setattr(row, key, value)
                session.commit()

    def dashboard_summary(self, mode: str) -> dict[str, Any]:
        trades = self.list_trades(10000, mode)
        pnls = [float(item["pnl"]) for item in trades]
        wins = sum(value > 0 for value in pnls)
        balance = self.latest_balance(mode)
        positions = self.open_positions(mode)
        today = datetime.now(UTC).date()
        today_pnl = sum(
            float(item["pnl"]) for item in trades if item["executed_at"].date() == today
        )
        with self.database.session() as session:
            equities = list(
                session.scalars(
                    select(BalanceModel.equity)
                    .where(BalanceModel.mode == mode)
                    .order_by(BalanceModel.timestamp)
                ).all()
            )
        peak = 0.0
        maximum_drawdown = 0.0
        for value in equities:
            equity = float(value)
            peak = max(peak, equity)
            if peak > 0:
                maximum_drawdown = max(maximum_drawdown, (peak - equity) / peak)
        return {
            "balance": float(balance["free"]) if balance else 0.0,
            "equity": float(balance["equity"]) if balance else 0.0,
            "today_pnl": today_pnl,
            "gross_pnl": sum(float(item["gross_pnl"]) for item in trades),
            "total_pnl": sum(pnls),
            "total_fees": sum(float(item["fees"]) for item in trades),
            "maximum_drawdown": maximum_drawdown,
            "open_positions": len(positions),
            "win_rate": wins / len(pnls) if pnls else 0.0,
            "trades": len(pnls),
        }
