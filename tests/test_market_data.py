from __future__ import annotations

import pandas as pd
import pytest

from app.exchange.market_data import MarketDataError, validate_candles


def test_valid_candles(candles: pd.DataFrame) -> None:
    result = validate_candles(candles)
    assert len(result) == len(candles)
    assert str(result.timestamp.dt.tz) == "UTC"


@pytest.mark.parametrize(
    "mutation", ["duplicate", "negative_volume", "bad_high", "nan", "unordered"]
)
def test_bad_candles_rejected(candles: pd.DataFrame, mutation: str) -> None:
    frame = candles.copy()
    if mutation == "duplicate":
        frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    elif mutation == "negative_volume":
        frame.loc[1, "volume"] = -1
    elif mutation == "bad_high":
        frame.loc[1, "high"] = frame.loc[1, "low"] - 1
    elif mutation == "nan":
        frame.loc[1, "close"] = float("nan")
    else:
        frame = frame.iloc[::-1]
    with pytest.raises(MarketDataError):
        validate_candles(frame)
