from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd


def _annualization_factor(timestamps: pd.Series) -> float:
    if len(timestamps) < 2:
        return 1.0
    diffs = pd.to_datetime(timestamps, utc=True).diff().dropna()
    if diffs.empty or diffs.median() <= timedelta(0):
        return 1.0
    seconds = diffs.median().total_seconds()
    return math.sqrt((365.0 * 24 * 3600) / seconds)


def calculate_metrics(
    initial_capital: float,
    final_capital: float,
    trades: list[dict[str, Any]],
    equity_curve: pd.DataFrame,
) -> dict[str, Any]:
    pnls = np.array([float(t["net_pnl"]) for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    count = len(pnls)
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    profit_factor = (
        gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    )

    if equity_curve.empty:
        max_drawdown = sharpe = sortino = 0.0
    else:
        equities = equity_curve["equity"].astype(float)
        peak = equities.cummax()
        drawdowns = (equities - peak) / peak.replace(0, np.nan)
        max_drawdown = abs(float(drawdowns.min())) if not drawdowns.empty else 0.0
        returns = equities.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        annualizer = _annualization_factor(equity_curve["timestamp"])
        sharpe = (
            float(returns.mean() / returns.std(ddof=1) * annualizer)
            if len(returns) > 1 and returns.std(ddof=1) > 0
            else 0.0
        )
        downside = returns[returns < 0]
        sortino = (
            float(returns.mean() / downside.std(ddof=1) * annualizer)
            if len(downside) > 1 and downside.std(ddof=1) > 0
            else 0.0
        )

    holding_seconds = [float(t.get("holding_seconds", 0)) for t in trades]
    fees = sum(float(t.get("fees", 0)) for t in trades)
    gross_pnl = sum(float(t.get("gross_pnl", 0)) for t in trades)
    net_pnl = sum(float(t.get("net_pnl", 0)) for t in trades)
    average_win = float(wins.mean()) if len(wins) else 0.0
    average_loss = float(losses.mean()) if len(losses) else 0.0
    win_rate = len(wins) / count if count else 0.0
    expectancy = win_rate * average_win + (1 - win_rate) * average_loss if count else 0.0
    return {
        "initial_capital": initial_capital,
        "final_capital": final_capital,
        "total_return": (final_capital / initial_capital - 1) if initial_capital else 0.0,
        "total_trades": count,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "maximum_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "average_trade": float(pnls.mean()) if count else 0.0,
        "average_win": average_win,
        "average_loss": average_loss,
        "expectancy": expectancy,
        "largest_win": float(wins.max()) if len(wins) else 0.0,
        "largest_loss": float(losses.min()) if len(losses) else 0.0,
        "average_holding_seconds": float(np.mean(holding_seconds)) if holding_seconds else 0.0,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "total_fees": fees,
    }
