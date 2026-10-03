from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import Settings, TradingMode


def test_safe_paper_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.trading_mode is TradingMode.PAPER
    assert settings.default_symbol == "BTC/USDT"
    assert "api_secret" not in settings.safe_summary()


def test_live_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="requires API_KEY"):
        Settings(_env_file=None, trading_mode="live")


def test_configuration_relationship_validation() -> None:
    with pytest.raises(ValidationError, match="EMA_FAST"):
        Settings(_env_file=None, ema_fast=50, ema_slow=20)
    with pytest.raises(ValidationError, match="loopback"):
        Settings(_env_file=None, dashboard_host="0.0.0.0")
