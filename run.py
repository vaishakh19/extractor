#!/usr/bin/env python3
"""Local Crypto Bot command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import ValidationError
from rich.table import Table

from app.backtest.engine import BacktestConfig, BacktestEngine
from app.backtest.report import save_report, text_report
from app.config.logging import configure_logging
from app.config.settings import Settings, StrategyName, TradingMode
from app.database.database import Database
from app.database.repositories import Repository
from app.exchange.ccxt_client import CCXTClient
from app.exchange.market_data import COLUMNS, validate_candles
from app.main import KILL_SWITCH, TradingBot
from app.strategy.strategy_manager import StrategyManager
from app.utils.terminal import console


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Privacy-focused local crypto trading bot (paper mode by default)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    commands = result.add_mutually_exclusive_group()
    commands.add_argument("--paper", action="store_true", help="run with simulated funds")
    commands.add_argument("--live", action="store_true", help="request guarded real-order mode")
    commands.add_argument("--backtest", action="store_true", help="run an event-driven backtest")
    commands.add_argument(
        "--dashboard", action="store_true", help="serve the loopback-only dashboard"
    )
    commands.add_argument(
        "--status", action="store_true", help="show persisted local status and exit"
    )
    commands.add_argument("--kill", action="store_true", help="activate the persistent kill switch")

    result.add_argument("--csv", type=Path, help="historical OHLCV CSV for --backtest")
    result.add_argument("--strategy", choices=[item.value for item in StrategyName])
    result.add_argument("--symbol", help="CCXT symbol such as BTC/USDT")
    result.add_argument("--timeframe", help="candle timeframe such as 5m or 1h")
    result.add_argument("--start", help="backtest start time/date in UTC")
    result.add_argument("--end", help="backtest end time/date in UTC")
    result.add_argument("--initial-capital", type=float, help="backtest starting capital")
    return result


def load_settings(mode: TradingMode | None = None) -> Settings:
    kwargs = {"trading_mode": mode} if mode is not None else {}
    return Settings(**kwargs)


def activate_kill_switch() -> int:
    KILL_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    KILL_SWITCH.write_text(f"activated_at={datetime.now(UTC).isoformat()}\n", encoding="utf-8")
    console.print(
        "[bold red]KILL SWITCH ACTIVE[/bold red] — all execution services now reject new orders."
    )
    return 0


def clear_kill_for_explicit_start() -> None:
    if KILL_SWITCH.exists():
        KILL_SWITCH.unlink()
        console.print("[yellow]Previous kill switch cleared for this explicit new run.[/yellow]")


def confirm_live() -> bool:
    console.print(
        "\n[bold red]WARNING:\nLIVE TRADING WILL USE REAL MONEY.[/bold red]\n"
        "Use trading-only API credentials. Withdrawal permission must be disabled.\n"
        "An exchange-side stop is required, but no system can eliminate exchange or network risk."
    )
    try:
        confirmation = input("Type exactly I UNDERSTAND to continue: ")
    except EOFError:
        return False
    return confirmation == "I UNDERSTAND"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"CSV not found: {path}")
    frame = pd.read_csv(path)
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
    numeric = pd.to_numeric(frame["timestamp"], errors="coerce")
    if numeric.notna().all():
        unit = "ms" if numeric.abs().median() > 10_000_000_000 else "s"
        frame["timestamp"] = pd.to_datetime(numeric, unit=unit, utc=True)
    else:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    return validate_candles(frame)


async def download_candles(
    settings: Settings, symbol: str, timeframe: str, start: str | None, end: str | None
) -> pd.DataFrame:
    client = CCXTClient(settings)
    await client.connect()
    try:

        def utc_milliseconds(value: str) -> int:
            stamp = pd.Timestamp(value)
            stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
            return int(stamp.timestamp() * 1000)

        since = utc_milliseconds(start) if start else None
        end_ms = utc_milliseconds(end) if end else None
        rows: list[list[float]] = []
        while True:
            batch = await client.get_ohlcv(
                symbol, timeframe, limit=min(settings.candle_limit, 1000), since=since
            )
            if not batch:
                break
            rows.extend(batch)
            next_since = int(batch[-1][0]) + 1
            if since is None or next_since <= since or (end_ms and next_since > end_ms):
                break
            since = next_since
            if len(rows) >= 100_000:
                raise ValueError("download safety limit of 100,000 candles reached")
        frame = pd.DataFrame(rows, columns=COLUMNS)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        if end_ms:
            frame = frame[frame["timestamp"] <= pd.to_datetime(end_ms, unit="ms", utc=True)]
        frame = frame.drop_duplicates("timestamp").sort_values("timestamp")
        return validate_candles(frame)
    finally:
        await client.close()


def run_backtest(args: argparse.Namespace, settings: Settings) -> int:
    symbol = (args.symbol or settings.default_symbol).upper()
    timeframe = args.timeframe or settings.timeframe
    strategy_name = args.strategy or settings.strategy.value
    if args.csv:
        candles = read_csv(args.csv)
    else:
        console.print("Downloading public historical candles locally…")
        candles = asyncio.run(download_candles(settings, symbol, timeframe, args.start, args.end))
        path = Path("data/historical") / f"{symbol.replace('/', '-')}_{timeframe}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        candles.to_csv(path, index=False)
        console.print(f"Saved validated candles to [cyan]{path}[/cyan]")
    strategy = StrategyManager().create(strategy_name, settings)
    config = BacktestConfig(
        symbol=symbol,
        timeframe=timeframe,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.initial_capital or settings.initial_paper_balance,
        fee_rate=settings.paper_fee_rate,
        slippage_bps=settings.paper_slippage_bps,
        risk_per_trade=settings.risk_per_trade,
        max_daily_loss=settings.max_daily_loss,
        max_position_percent=settings.max_position_percent,
        stop_loss_percent=settings.stop_loss_percent,
        take_profit_percent=settings.take_profit_percent,
    )
    result = BacktestEngine(strategy, config).run(candles)
    paths = save_report(result)
    database = Database(settings.database_url)
    database.initialize()
    repository = Repository(database)
    repository.save_backtest(
        symbol,
        timeframe,
        strategy.name,
        asdict(config),
        result.metrics,
        str(paths["json"]),
    )
    database.close()
    console.print("\n[bold cyan]BACKTEST RESULTS[/bold cyan]")
    console.print(text_report(result))
    console.print(f"\nReports: [cyan]{paths['json']}[/cyan], [cyan]{paths['equity']}[/cyan]")
    console.print("[yellow]Historical results do not imply future profitability.[/yellow]")
    return 0


def show_status(settings: Settings) -> int:
    database = Database(settings.database_url)
    database.initialize()
    repository = Repository(database)
    table = Table(title="LOCAL CRYPTO BOT STATUS", show_header=False)
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("Configured mode", settings.trading_mode.value.upper())
    table.add_row("Kill switch", "ACTIVE" if KILL_SWITCH.exists() else "inactive")
    table.add_row("Exchange", settings.exchange)
    table.add_row("Symbol", settings.default_symbol)
    for mode in ("paper", "live"):
        summary = repository.dashboard_summary(mode)
        table.add_row(
            f"{mode.title()} account",
            f"equity ${summary['equity']:,.2f} · {summary['open_positions']} positions · {summary['trades']} trades",
        )
    console.print(table)
    events = repository.list_events(5)
    if events:
        console.print("\n[bold]Recent events[/bold]")
        for event in events:
            console.print(
                f"[dim]{event['timestamp']}[/dim] [{event['level']}] {event['event_type']}: {event['message']}"
            )
    database.close()
    return 0


def serve_dashboard(settings: Settings) -> int:
    import uvicorn

    from app.dashboard import create_dashboard

    database = Database(settings.database_url)
    database.initialize()
    app = create_dashboard(settings, Repository(database))
    console.print(
        f"Dashboard is local-only: [cyan]http://{settings.dashboard_host}:{settings.dashboard_port}[/cyan]"
    )
    uvicorn.run(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level=settings.log_level.lower(),
    )
    database.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.kill:
        return activate_kill_switch()
    try:
        if args.live:
            if not confirm_live():
                console.print("[yellow]LIVE mode cancelled. No order was sent.[/yellow]")
                return 2
            settings = load_settings(TradingMode.LIVE)
        elif args.backtest:
            settings = load_settings(TradingMode.BACKTEST)
        elif args.dashboard or args.status:
            settings = load_settings()
        else:
            # No flag is always paper, even if .env says LIVE.
            settings = load_settings(TradingMode.PAPER)
        configure_logging(settings)
        if args.backtest:
            return run_backtest(args, settings)
        if args.dashboard:
            return serve_dashboard(settings)
        if args.status:
            return show_status(settings)
        clear_kill_for_explicit_start()
        bot = TradingBot(settings, live_confirmed=args.live)
        try:
            asyncio.run(bot.run())
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped by user.[/yellow]")
        return 0
    except (ValidationError, ValueError) as exc:
        console.print(f"[bold red]Configuration/input error:[/bold red] {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary guarantees a safe local shutdown
        console.print(f"[bold red]Safe shutdown after error:[/bold red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
