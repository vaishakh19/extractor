from __future__ import annotations

from collections.abc import Callable

from app.config.settings import Settings, StrategyName
from app.strategy.base import Strategy
from app.strategy.combined import CombinedStrategy
from app.strategy.ema_cross import EMACrossStrategy
from app.strategy.rsi import RSIStrategy

StrategyFactory = Callable[[Settings], Strategy]


class StrategyManager:
    def __init__(self) -> None:
        self._registry: dict[str, StrategyFactory] = {}
        self.register("ema_cross", lambda s: EMACrossStrategy(s.ema_fast, s.ema_slow))
        self.register("rsi", lambda s: RSIStrategy(s.rsi_period, s.rsi_oversold, s.rsi_overbought))
        self.register(
            "combined",
            lambda s: CombinedStrategy(
                s.ema_fast,
                s.ema_slow,
                s.rsi_period,
                s.rsi_oversold,
                s.rsi_overbought,
                s.volume_period,
                s.volume_multiplier,
            ),
        )

    def register(self, name: str, factory: StrategyFactory) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("strategy name cannot be empty")
        self._registry[normalized] = factory

    def create(self, name: str | StrategyName, settings: Settings) -> Strategy:
        key = name.value if isinstance(name, StrategyName) else name.strip().lower()
        try:
            return self._registry[key](settings)
        except KeyError as exc:
            raise ValueError(
                f"unknown strategy {key!r}; available: {', '.join(self.available())}"
            ) from exc

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))
