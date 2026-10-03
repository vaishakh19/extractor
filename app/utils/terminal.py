from __future__ import annotations

from typing import Any

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.config.settings import Settings

console = Console()


def first_run_panel(settings: Settings) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan")
    grid.add_column()
    grid.add_row("Mode", settings.trading_mode.value.upper())
    grid.add_row("Exchange", settings.exchange.title())
    grid.add_row("Symbol", settings.default_symbol)
    grid.add_row("Starting paper balance", f"${settings.initial_paper_balance:,.2f}")
    grid.add_row("Strategy", settings.strategy.value)
    grid.add_row("Risk per trade", f"{settings.risk_per_trade:.1%}")
    grid.add_row("Maximum daily loss", f"{settings.max_daily_loss:.1%}")
    body = Group(Align.center(Text("LOCAL CRYPTO TRADING BOT", style="bold white")), Text(""), grid)
    return Panel(body, border_style="cyan", subtitle="Press Ctrl+C to stop", padding=(1, 3))


def status_panel(settings: Settings, status: dict[str, Any]) -> Panel:
    grid = Table.grid(padding=(0, 2), expand=True)
    grid.add_column(style="bold cyan")
    grid.add_column(justify="right")
    mode = settings.trading_mode.value.upper()
    mode_style = "bold red" if mode == "LIVE" else "bold green"
    grid.add_row("Mode", Text(mode, style=mode_style))
    grid.add_row("Exchange", settings.exchange.title())
    grid.add_row("Symbol", settings.default_symbol)
    price = status.get("price")
    grid.add_row("Price", f"${price:,.2f}" if price else "waiting…")
    grid.add_row("Balance", f"${status.get('balance', 0):,.2f}")
    grid.add_row("Equity", f"${status.get('equity', 0):,.2f}")
    grid.add_row("P&L", f"${status.get('pnl', 0):+,.2f}")
    grid.add_row("Position", status.get("position", "FLAT"))
    grid.add_row("Strategy", settings.strategy.value)
    grid.add_row("Last signal", status.get("last_signal", "waiting…"))
    return Panel(grid, title="[bold]LOCAL CRYPTO BOT[/bold]", border_style="cyan")
