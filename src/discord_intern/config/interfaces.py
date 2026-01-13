from __future__ import annotations

from typing import Protocol

from discord_intern.config.models import AppConfig, ConfigLoadRequest


class ConfigLoader(Protocol):
    """
    Loads effective runtime configuration.

    Implementations must follow the precedence and override mapping rules described in:
    - docs/configuration.md
    """

    async def load(self, request: ConfigLoadRequest = ConfigLoadRequest()) -> AppConfig:
        ...

