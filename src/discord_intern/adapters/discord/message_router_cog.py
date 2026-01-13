from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable, Optional, TypeVar

import aiohttp
import discord
from discord.ext import commands

from discord_intern.ai.interfaces import AIClient
from discord_intern.config.models import DiscordSettings
from discord_intern.core.models import Conversation, Message, RequestContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _to_utc_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_messages(messages: Iterable[discord.Message], *, bot_user_id: int) -> list[Message]:
    out: list[Message] = []
    for m in messages:
        text = (m.content or "").strip()
        if not text:
            continue
        role = "assistant" if m.author and m.author.id == bot_user_id else "user"
        out.append(
            Message(
                role=role,
                text=text,
                timestamp=_to_utc_datetime(m.created_at),
                author_id=str(m.author.id) if m.author is not None else None,
            )
        )
    return out


def _thread_name_from_message(text: str) -> str:
    base = text.strip().replace("\n", " ")
    if not base:
        return "FAQ Answer"
    base = base[:80]
    return f"FAQ: {base}"


_RETRYABLE_DISCORD_HTTP_ERRORS: tuple[type[BaseException], ...] = (
    aiohttp.ClientConnectorError,
    aiohttp.ClientOSError,
    aiohttp.ServerDisconnectedError,
    asyncio.TimeoutError,
    ConnectionResetError,
)


async def _retry_async(
    operation: str,
    *,
    attempts: int,
    base_delay_seconds: float,
    make_call: Callable[[], Awaitable[T]],
    log_context: str,
) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await make_call()
        except _RETRYABLE_DISCORD_HTTP_ERRORS as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay_seconds = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "discord.http_retry operation=%s attempt=%s/%s delay_seconds=%s %s error=%s",
                operation,
                attempt,
                attempts,
                delay_seconds,
                log_context,
                type(exc).__name__,
            )
            await asyncio.sleep(delay_seconds)

    assert last_error is not None
    raise last_error


class MessageRouterCog(commands.Cog):
    """
    Routes Discord events to the AI module and posts replies in threads.

    This implements the behavior specified in docs/module-bot-integration.md.
    """

    def __init__(self, *, bot: commands.Bot, ai_client: AIClient, settings: DiscordSettings, dry_run: bool) -> None:
        self._bot = bot
        self._ai = ai_client
        self._settings = settings
        self._dry_run = dry_run

    @property
    def ai_client(self) -> AIClient:
        return self._ai

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author is not None and message.author.bot:
            return

        content = (message.content or "").strip()
        if not content:
            return

        bot_user = self._bot.user
        if bot_user is None:
            logger.warning("discord.bot_user_missing message_id=%s", getattr(message, "id", None))
            return
        bot_user_id = bot_user.id

        if isinstance(message.channel, discord.Thread):
            await self._handle_thread_message(message=message, thread=message.channel, bot_user_id=bot_user_id)
        else:
            await self._handle_channel_message(message=message, bot_user_id=bot_user_id)

        await self._bot.process_commands(message)

    async def _handle_channel_message(self, *, message: discord.Message, bot_user_id: int) -> None:
        if message.guild is None:
            return

        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        conversation = Conversation(
            messages=(
                Message(
                    role="user",
                    text=(message.content or "").strip(),
                    timestamp=_to_utc_datetime(message.created_at),
                    author_id=str(message.author.id) if message.author is not None else None,
                ),
            )
        )

        context = RequestContext(
            platform="discord",
            guild_id=str(message.guild.id),
            channel_id=str(channel_id),
            thread_id=None,
            message_id=str(message.id),
        )

        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._ai.generate_reply(conversation=conversation, context=context),
                timeout=self._settings.ai_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "ai.timeout platform=discord guild_id=%s channel_id=%s message_id=%s timeout_seconds=%s",
                context.guild_id,
                context.channel_id,
                context.message_id,
                self._settings.ai_timeout_seconds,
            )
            return
        except Exception:
            logger.exception(
                "ai.error platform=discord guild_id=%s channel_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.message_id,
            )
            return
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "ai.call platform=discord routing=channel_message guild_id=%s channel_id=%s message_id=%s latency_ms=%s",
                context.guild_id,
                context.channel_id,
                context.message_id,
                elapsed_ms,
            )

        if not result.should_reply or not result.reply_text:
            return

        if self._dry_run:
            logger.info(
                "discord.dry_run_reply platform=discord guild_id=%s channel_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.message_id,
            )
            return

        thread_name = _thread_name_from_message(message.content or "")
        log_context = (
            f"platform=discord guild_id={context.guild_id} channel_id={context.channel_id} message_id={context.message_id}"
        )
        try:
            thread = await _retry_async(
                "create_thread",
                attempts=3,
                base_delay_seconds=0.5,
                make_call=lambda: message.create_thread(name=thread_name),
                log_context=log_context,
            )
        except _RETRYABLE_DISCORD_HTTP_ERRORS:
            logger.exception("discord.thread_create_gave_up %s", log_context)
            return
        except discord.DiscordException:
            logger.exception(
                "discord.thread_create_failed platform=discord guild_id=%s channel_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.message_id,
            )
            return

        try:
            await _retry_async(
                "post_message",
                attempts=3,
                base_delay_seconds=0.5,
                make_call=lambda: thread.send(result.reply_text),
                log_context=f"{log_context} thread_id={thread.id}",
            )
        except _RETRYABLE_DISCORD_HTTP_ERRORS:
            logger.exception("discord.thread_post_gave_up %s thread_id=%s", log_context, str(thread.id))
            return
        except discord.DiscordException:
            logger.exception(
                "discord.thread_post_failed platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                str(thread.id),
                context.message_id,
            )
            return

        logger.info(
            "discord.replied platform=discord routing=channel_message guild_id=%s channel_id=%s thread_id=%s message_id=%s",
            context.guild_id,
            context.channel_id,
            str(thread.id),
            context.message_id,
        )

    async def _handle_thread_message(self, *, message: discord.Message, thread: discord.Thread, bot_user_id: int) -> None:
        history: list[discord.Message]
        try:
            history = [m async for m in thread.history(limit=None, oldest_first=True)]
        except discord.DiscordException:
            logger.exception(
                "discord.thread_history_failed platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s",
                str(thread.guild.id) if thread.guild is not None else None,
                str(thread.parent_id) if thread.parent_id is not None else str(thread.id),
                str(thread.id),
                str(message.id),
            )
            return

        is_eligible = any(m.author is not None and m.author.id == bot_user_id for m in history)
        if not is_eligible:
            return

        normalized = _normalize_messages(history, bot_user_id=bot_user_id)
        if not normalized:
            return

        channel_id = str(thread.parent_id) if thread.parent_id is not None else str(thread.id)
        context = RequestContext(
            platform="discord",
            guild_id=str(thread.guild.id) if thread.guild is not None else None,
            channel_id=channel_id,
            thread_id=str(thread.id),
            message_id=str(message.id),
        )

        conversation = Conversation(messages=normalized)

        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._ai.generate_reply(conversation=conversation, context=context),
                timeout=self._settings.ai_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "ai.timeout platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s timeout_seconds=%s",
                context.guild_id,
                context.channel_id,
                context.thread_id,
                context.message_id,
                self._settings.ai_timeout_seconds,
            )
            return
        except Exception:
            logger.exception(
                "ai.error platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.thread_id,
                context.message_id,
            )
            return
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "ai.call platform=discord routing=thread_update guild_id=%s channel_id=%s thread_id=%s message_id=%s latency_ms=%s",
                context.guild_id,
                context.channel_id,
                context.thread_id,
                context.message_id,
                elapsed_ms,
            )

        if not result.should_reply or not result.reply_text:
            return

        if self._dry_run:
            logger.info(
                "discord.dry_run_reply platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.thread_id,
                context.message_id,
            )
            return

        try:
            await _retry_async(
                "post_message",
                attempts=3,
                base_delay_seconds=0.5,
                make_call=lambda: thread.send(result.reply_text),
                log_context=(
                    f"platform=discord guild_id={context.guild_id} channel_id={context.channel_id} "
                    f"thread_id={context.thread_id} message_id={context.message_id}"
                ),
            )
        except _RETRYABLE_DISCORD_HTTP_ERRORS:
            logger.exception(
                "discord.thread_post_gave_up platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.thread_id,
                context.message_id,
            )
            return
        except discord.DiscordException:
            logger.exception(
                "discord.thread_post_failed platform=discord guild_id=%s channel_id=%s thread_id=%s message_id=%s",
                context.guild_id,
                context.channel_id,
                context.thread_id,
                context.message_id,
            )
            return

        logger.info(
            "discord.replied platform=discord routing=thread_update guild_id=%s channel_id=%s thread_id=%s message_id=%s",
            context.guild_id,
            context.channel_id,
            context.thread_id,
            context.message_id,
        )
