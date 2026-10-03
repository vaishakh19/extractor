from __future__ import annotations

import json
from pathlib import Path

from app.backtest.engine import BacktestResult


def save_report(
    result: BacktestResult, output_dir: str | Path = "backtest_reports"
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{result.config.symbol.replace('/', '-')}_{result.config.timeframe}_{result.strategy}"
    json_path = directory / f"{stem}.json"
    equity_path = directory / f"{stem}_equity.csv"
    payload = result.serializable()
    payload["metrics"] = {
        key: ("inf" if value == float("inf") else "-inf" if value == float("-inf") else value)
        for key, value in payload["metrics"].items()
    }
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    result.equity_curve.to_csv(equity_path, index=False)
    return {"json": json_path, "equity": equity_path}


def text_report(result: BacktestResult) -> str:
    metrics = result.metrics
    profit_factor = metrics["profit_factor"]
    pf_text = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    return "\n".join(
        [
            f"Strategy:         {result.strategy}",
            f"Initial capital: ${metrics['initial_capital']:,.2f}",
            f"Final capital:   ${metrics['final_capital']:,.2f}",
            f"Total return:    {metrics['total_return']:.2%}",
            f"Trades:          {metrics['total_trades']}",
            f"Win rate:        {metrics['win_rate']:.2%}",
            f"Profit factor:   {pf_text}",
            f"Max drawdown:    {metrics['maximum_drawdown']:.2%}",
            f"Sharpe ratio:    {metrics['sharpe_ratio']:.2f}",
            f"Sortino ratio:   {metrics['sortino_ratio']:.2f}",
            f"Gross P&L:       ${metrics['gross_pnl']:,.2f}",
            f"Fees:            ${metrics['total_fees']:,.2f}",
            f"Net P&L:         ${metrics['net_pnl']:,.2f}",
        ]
    )
