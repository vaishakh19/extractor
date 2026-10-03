from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("crypto_bot.notifications")


class Notifier(ABC):
    @abstractmethod
    async def send(self, subject: str, message: str) -> None: ...


class NullNotifier(Notifier):
    """Default local no-op notifier; external services are never required."""

    async def send(self, subject: str, message: str) -> None:
        logger.debug("notification disabled: %s", subject)


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier] | None = None) -> None:
        self.notifiers = notifiers or []

    async def send(self, subject: str, message: str) -> None:
        for notifier in self.notifiers:
            try:
                await notifier.send(subject, message)
            except Exception:
                logger.exception("optional notification failed")
