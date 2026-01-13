from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from discord_intern.adapters.discord.interfaces import DiscordAdapter
from discord_intern.adapters.discord.message_router_cog import MessageRouterCog
from discord_intern.ai.interfaces import AIClient
from discord_intern.config.models import AppConfig

logger = logging.getLogger(__name__)


def _build_intents() -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    return intents


class _InternBot(commands.Bot):
    def __init__(self, *, config: AppConfig, ai_client: AIClient) -> None:
        intents = _build_intents()
        super().__init__(command_prefix="!", intents=intents)

        self._router_cog = MessageRouterCog(
            bot=self,
            ai_client=ai_client,
            settings=config.discord,
            dry_run=config.app.dry_run,
        )

    async def setup_hook(self) -> None:
        await self.add_cog(self._router_cog)

    async def on_ready(self) -> None:
        user = self.user
        logger.info(
            "discord.ready user_id=%s user=%s",
            str(user.id) if user is not None else None,
            str(user) if user is not None else None,
        )


class DiscordBotAdapter(DiscordAdapter):
    def __init__(self, *, config: AppConfig, ai_client: AIClient) -> None:
        self._config = config
        self._ai_client = ai_client

        self._bot = _InternBot(config=self._config, ai_client=self._ai_client)

    @property
    def ai_client(self) -> AIClient:
        return self._ai_client

    async def start(self) -> None:
        logger.info(
            "discord.adapter_starting dry_run=%s ai_timeout_seconds=%s",
            self._config.app.dry_run,
            self._config.discord.ai_timeout_seconds,
        )
        await self._bot.start(self._config.discord.token)

    async def run_for(self, *, seconds: float, ready_timeout_seconds: float = 30) -> None:
        logger.info(
            "discord.adapter_starting dry_run=%s ai_timeout_seconds=%s run_for_seconds=%s",
            self._config.app.dry_run,
            self._config.discord.ai_timeout_seconds,
            seconds,
        )

        await self._bot.login(self._config.discord.token)
        connect_task = asyncio.create_task(self._bot.connect(reconnect=True))
        try:
            await asyncio.wait_for(self._bot.wait_until_ready(), timeout=ready_timeout_seconds)
            await asyncio.sleep(seconds)
        finally:
            await self.stop()
            if not connect_task.done():
                connect_task.cancel()
            try:
                await connect_task
            except asyncio.CancelledError:
                logger.info("discord.connect_task_cancelled")

    async def stop(self) -> None:
        if not self._bot.is_closed():
            await self._bot.close()
