"""Validated, local-only application configuration."""

from __future__ import annotations

import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class StrategyName(str, Enum):
    EMA_CROSS = "ema_cross"
    RSI = "rsi"
    COMBINED = "combined"


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}/[A-Z0-9][A-Z0-9._-]{0,19}(?::[A-Z0-9._-]+)?$")
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]*[mhdwM]$")


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional local ``.env`` file.

    Secret values use :class:`SecretStr`, are excluded from repr, and must never be
    passed to application logging.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_assignment=True,
    )

    exchange: str = Field(default="binance", min_length=1, max_length=40)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    api_secret: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    api_password: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)

    trading_mode: TradingMode = TradingMode.PAPER
    default_symbol: str = "BTC/USDT"
    timeframe: str = "5m"
    strategy: StrategyName = StrategyName.COMBINED
    poll_interval_seconds: float = Field(default=15.0, ge=1.0, le=3600.0)
    candle_limit: int = Field(default=250, ge=60, le=5000)

    initial_paper_balance: float = Field(default=1000.0, gt=0)
    paper_fee_rate: float = Field(default=0.001, ge=0, le=0.1)
    paper_slippage_bps: float = Field(default=5.0, ge=0, le=1000)
    paper_partial_fill_ratio: float = Field(default=1.0, gt=0, le=1)

    risk_per_trade: float = Field(default=0.01, gt=0, le=0.1)
    max_daily_loss: float = Field(default=0.03, gt=0, le=0.5)
    max_open_positions: int = Field(default=3, ge=1, le=100)
    max_position_percent: float = Field(default=0.25, gt=0, le=1)
    stop_loss_percent: float = Field(default=1.0, gt=0, le=50)
    take_profit_percent: float = Field(default=2.0, gt=0, le=100)

    ema_fast: int = Field(default=20, ge=2, le=1000)
    ema_slow: int = Field(default=50, ge=3, le=2000)
    rsi_period: int = Field(default=14, ge=2, le=1000)
    rsi_oversold: float = Field(default=30.0, ge=0, le=100)
    rsi_overbought: float = Field(default=70.0, ge=0, le=100)
    volume_period: int = Field(default=20, ge=2, le=1000)
    volume_multiplier: float = Field(default=1.0, gt=0, le=100)

    database_url: str = "sqlite:///data/bot.db"
    log_level: str = "INFO"
    log_file: Path = Path("logs/bot.log")
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = Field(default=8000, ge=1, le=65535)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_retries: int = Field(default=5, ge=0, le=20)

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]+", value):
            raise ValueError("exchange must contain only letters, numbers, underscores, or hyphens")
        return value

    @field_validator("default_symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not _SYMBOL_RE.fullmatch(value):
            raise ValueError("symbol must use CCXT BASE/QUOTE notation, for example BTC/USDT")
        return value

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        value = value.strip()
        if not _TIMEFRAME_RE.fullmatch(value):
            raise ValueError("timeframe must look like 1m, 5m, 1h, 1d, or 1w")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid LOG_LEVEL")
        return value

    @field_validator("dashboard_host")
    @classmethod
    def local_dashboard_only(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("dashboard must bind to a loopback address for safety")
        return value

    @model_validator(mode="after")
    def validate_related_values(self) -> Settings:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("EMA_FAST must be less than EMA_SLOW")
        if self.rsi_oversold >= self.rsi_overbought:
            raise ValueError("RSI_OVERSOLD must be less than RSI_OVERBOUGHT")
        if self.trading_mode is TradingMode.LIVE and (
            not self.api_key.get_secret_value() or not self.api_secret.get_secret_value()
        ):
            raise ValueError("LIVE mode requires API_KEY and API_SECRET")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("only local SQLite DATABASE_URL values are supported")
        return self

    def safe_summary(self) -> dict[str, object]:
        """Return public settings suitable for status output and logs."""
        return {
            "exchange": self.exchange,
            "trading_mode": self.trading_mode.value,
            "default_symbol": self.default_symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy.value,
            "risk_per_trade": self.risk_per_trade,
            "max_daily_loss": self.max_daily_loss,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "volume_period": self.volume_period,
            "volume_multiplier": self.volume_multiplier,
            "has_api_credentials": bool(
                self.api_key.get_secret_value() and self.api_secret.get_secret_value()
            ),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
