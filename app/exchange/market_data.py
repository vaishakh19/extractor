"""Validated market data acquisition and reconnecting local stream."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from app.exchange.base import ExchangeClient, ExchangeUnavailable, Ticker
from app.utils.time import timeframe_seconds

logger = logging.getLogger("crypto_bot.exchange.market_data")
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class MarketDataError(ValueError):
    pass


def validate_candles(data: pd.DataFrame) -> pd.DataFrame:
    """Validate candles strictly; malformed data is rejected rather than traded."""
    missing_columns = set(COLUMNS) - set(data.columns)
    if missing_columns:
        raise MarketDataError(f"missing candle columns: {sorted(missing_columns)}")
    frame = data[COLUMNS].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    numeric = ["open", "high", "low", "close", "volume"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    if frame.isna().any().any():
        raise MarketDataError("candles contain NaN or invalid timestamps")
    if frame["timestamp"].duplicated().any():
        raise MarketDataError("duplicate candle timestamps detected")
    if not frame["timestamp"].is_monotonic_increasing:
        raise MarketDataError("candles are out of order")
    if not np.isfinite(frame[numeric].to_numpy()).all():
        raise MarketDataError("candles contain non-finite values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise MarketDataError("candle prices must be positive")
    if (frame["volume"] < 0).any():
        raise MarketDataError("candle volume cannot be negative")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise MarketDataError("candle high is inconsistent")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise MarketDataError("candle low is inconsistent")
    return frame.reset_index(drop=True)


class MarketDataService:
    def __init__(self, client: ExchangeClient, poll_interval: float = 15.0) -> None:
        self.client = client
        self.poll_interval = poll_interval

    async def candles(
        self, symbol: str, timeframe: str, limit: int = 500, since: int | None = None
    ) -> pd.DataFrame:
        raw = await self.client.get_ohlcv(symbol, timeframe, limit, since)
        frame = pd.DataFrame(raw, columns=COLUMNS)
        if not frame.empty:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return validate_candles(frame)

    async def stream_tickers(self, symbol: str) -> AsyncIterator[Ticker]:
        """Reconnect-capable REST ticker stream.

        CCXT's open-source client provides REST; this polling stream is the portable
        fallback. An exchange-specific WebSocket adapter can implement the same async
        iterator without changing the engine.
        """
        backoff = 1.0
        last_timestamp = None
        while True:
            try:
                ticker = await self.client.get_ticker(symbol)
                if ticker.timestamp != last_timestamp:
                    yield ticker
                    last_timestamp = ticker.timestamp
                backoff = 1.0
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                raise
            except ExchangeUnavailable as exc:
                logger.warning(
                    "market stream disconnected: %s; reconnecting in %.1fs", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except Exception:
                logger.exception("market stream error; reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def stream_closed_candles(
        self, symbol: str, timeframe: str, limit: int = 250
    ) -> AsyncIterator[pd.DataFrame]:
        """Yield each unseen closed candle with WebSocket preference and REST fallback."""
        last_seen = None
        backoff = 1.0
        websocket = self.client.supports_websocket_ohlcv()
        logger.info("candle stream transport: %s", "websocket" if websocket else "REST polling")
        while True:
            try:
                if websocket:
                    raw = await self.client.watch_ohlcv(symbol, timeframe, limit)
                    frame = pd.DataFrame(raw, columns=COLUMNS)
                    if not frame.empty:
                        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
                    frame = validate_candles(frame)
                else:
                    frame = await self.candles(symbol, timeframe, limit)
                # CCXT commonly includes the currently-forming candle. Trading on it
                # would produce unstable/repeated signals, so only emit closed bars.
                close_before = pd.Timestamp(datetime.now(UTC)) - pd.Timedelta(
                    seconds=timeframe_seconds(timeframe)
                )
                frame = frame[frame["timestamp"] <= close_before].reset_index(drop=True)
                if not frame.empty and frame.iloc[-1]["timestamp"] != last_seen:
                    last_seen = frame.iloc[-1]["timestamp"]
                    yield frame
                backoff = 1.0
                if not websocket:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("candle stream disconnected; retrying in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
