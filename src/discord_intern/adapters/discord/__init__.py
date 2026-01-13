"""Discord adapter contracts and implementations."""

from discord_intern.adapters.discord.bot_adapter import DiscordBotAdapter
from discord_intern.adapters.discord.message_router_cog import MessageRouterCog

__all__ = ["DiscordBotAdapter", "MessageRouterCog"]
