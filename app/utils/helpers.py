from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}/[A-Z0-9][A-Z0-9._-]{0,19}(?::[A-Z0-9._-]+)?$")


def validate_symbol(symbol: str) -> str:
    result = symbol.strip().upper()
    if not _SYMBOL.fullmatch(result):
        raise ValueError("invalid CCXT symbol")
    return result


def positive_decimal(value: object, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return number


def split_symbol(symbol: str) -> tuple[str, str]:
    normalized = validate_symbol(symbol)
    base, quote = normalized.split("/", maxsplit=1)
    return base, quote.split(":", maxsplit=1)[0]
