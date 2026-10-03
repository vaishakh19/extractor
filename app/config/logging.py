"""Structured logging with credential redaction and local rotation."""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.config.settings import Settings

_SENSITIVE = re.compile(
    r"(?i)(api[_-]?(?:key|secret|password)|authorization|token)"
    r"([\s\"']*[:=][\s\"']*)([^\s,;\"'}]+)"
)


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self.secrets = [secret for secret in (secrets or []) if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        message = _SENSITIVE.sub(r"\1\2[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for name in ("event", "symbol", "mode", "order_id"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(settings: Settings) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()

    redactor = RedactingFilter(
        [
            settings.api_key.get_secret_value(),
            settings.api_secret.get_secret_value(),
            settings.api_password.get_secret_value(),
        ]
    )
    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    console.addFilter(redactor)
    root.addHandler(console)

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(redactor)
    root.addHandler(file_handler)
    logging.Formatter.converter = __import__("time").gmtime
    return logging.getLogger("crypto_bot")
