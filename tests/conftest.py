from __future__ import annotations

from datetime import UTC

import pandas as pd
import pytest


@pytest.fixture
def candles() -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01", periods=80, freq="5min", tz=UTC)
    close = [100 + index * 0.1 for index in range(80)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": [1000.0] * 80,
        }
    )
