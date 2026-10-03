from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_iso() -> str:
    return utc_now().isoformat()


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def timeframe_seconds(timeframe: str) -> int:
    """Convert a validated CCXT timeframe to approximate seconds."""
    amount = int(timeframe[:-1])
    unit = timeframe[-1]
    multipliers = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000}
    try:
        return amount * multipliers[unit]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unsupported timeframe {timeframe!r}") from exc
