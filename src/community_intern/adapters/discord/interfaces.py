from __future__ import annotations

from typing import Protocol

from community_intern.ai_response import AIResponseService


class DiscordAdapter(Protocol):
    """
    A Discord-specific entry point.

    This is intentionally minimal: concrete implementations may be a CLI app, a service,
    or a discord.py Bot/Cog composition.
    """

    @property
    def ai_client(self) -> AIResponseService: ...

    async def start(self) -> None:
        """Start the adapter and connect to Discord."""

    async def stop(self) -> None:
        """Stop the adapter and disconnect cleanly."""




