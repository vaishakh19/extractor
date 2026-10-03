from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.backtest.engine import BacktestConfig, BacktestEngine
from app.backtest.report import save_report
from app.config.settings import Settings
from app.database.repositories import Repository
from app.exchange.market_data import validate_candles
from app.strategy.strategy_manager import StrategyManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Jinja2Templates(directory=PROJECT_ROOT / "dashboard" / "templates")


def create_dashboard(settings: Settings, repository: Repository) -> FastAPI:
    app = FastAPI(
        title="Local Crypto Bot",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.repository = repository
    app.mount(
        "/static", StaticFiles(directory=PROJECT_ROOT / "dashboard" / "static"), name="static"
    )

    @app.get("/", response_class=HTMLResponse)
    async def overview(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            _context(settings, repository),
        )

    @app.get("/api/status")
    async def api_status() -> dict[str, Any]:
        return _api_context(settings, repository)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "scope": "local-only"}

    @app.post("/backtest", response_class=HTMLResponse)
    async def run_backtest(
        request: Request,
        historical_file: Annotated[UploadFile, File()],
        strategy_name: Annotated[str, Form()] = "combined",
        symbol: Annotated[str, Form()] = "BTC/USDT",
        timeframe: Annotated[str, Form()] = "5m",
        initial_capital: Annotated[float, Form()] = 1000,
        fee_rate: Annotated[float, Form()] = 0.001,
        slippage_bps: Annotated[float, Form()] = 5,
        ema_fast: Annotated[int, Form()] = 20,
        ema_slow: Annotated[int, Form()] = 50,
        rsi_period: Annotated[int, Form()] = 14,
        rsi_oversold: Annotated[float, Form()] = 30,
        rsi_overbought: Annotated[float, Form()] = 70,
        volume_multiplier: Annotated[float, Form()] = 1.0,
    ) -> HTMLResponse:
        content = await historical_file.read(10_000_001)
        if len(content) > 10_000_000:
            raise HTTPException(413, "CSV is limited to 10 MB")
        try:
            frame = pd.read_csv(BytesIO(content))
            if "timestamp" not in frame:
                raise ValueError("CSV requires timestamp, open, high, low, close, volume columns")
            numeric_timestamps = pd.to_numeric(frame["timestamp"], errors="coerce")
            if numeric_timestamps.notna().all():
                unit = "ms" if numeric_timestamps.abs().median() > 10_000_000_000 else "s"
                frame["timestamp"] = pd.to_datetime(numeric_timestamps, unit=unit, utc=True)
            else:
                frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
            frame = validate_candles(frame)
            strategy_settings = settings.model_copy(
                update={
                    "ema_fast": ema_fast,
                    "ema_slow": ema_slow,
                    "rsi_period": rsi_period,
                    "rsi_oversold": rsi_oversold,
                    "rsi_overbought": rsi_overbought,
                    "volume_multiplier": volume_multiplier,
                }
            )
            strategy = StrategyManager().create(strategy_name, strategy_settings)
            config = BacktestConfig(
                symbol=symbol.upper(),
                timeframe=timeframe,
                initial_capital=initial_capital,
                fee_rate=fee_rate,
                slippage_bps=slippage_bps,
                risk_per_trade=settings.risk_per_trade,
                max_daily_loss=settings.max_daily_loss,
                max_position_percent=settings.max_position_percent,
                stop_loss_percent=settings.stop_loss_percent,
                take_profit_percent=settings.take_profit_percent,
            )
            result = BacktestEngine(strategy, config).run(frame)
            paths = save_report(result)
            repository.save_backtest(
                config.symbol,
                config.timeframe,
                strategy.name,
                parameters=result.serializable()["config"],
                metrics=result.metrics,
                report_path=str(paths["json"]),
            )
            context = _context(settings, repository)
            context["backtest_result"] = _finite_metrics(result.metrics)
        except (ValueError, KeyError, pd.errors.ParserError) as exc:
            context = _context(settings, repository)
            context["backtest_error"] = str(exc)
        return TEMPLATES.TemplateResponse(request, "index.html", context)

    return app


def _finite_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("∞" if isinstance(value, float) and math.isinf(value) else value)
        for key, value in metrics.items()
    }


def _api_context(settings: Settings, repository: Repository) -> dict[str, Any]:
    mode = settings.trading_mode.value
    summary = repository.dashboard_summary(mode)
    return {
        "bot_status": "KILLED" if Path("data/KILL_SWITCH").exists() else "READY / LOCAL",
        "mode": mode.upper(),
        "exchange": settings.exchange,
        "symbol": settings.default_symbol,
        "strategy": settings.strategy.value,
        **summary,
        "positions": repository.open_positions(mode),
        "trades_detail": repository.list_trades(100, mode),
        "events": repository.list_events(100),
        "backtests": repository.list_backtests(20),
    }


def _context(settings: Settings, repository: Repository) -> dict[str, Any]:
    return {"settings": settings.safe_summary(), **_api_context(settings, repository)}
