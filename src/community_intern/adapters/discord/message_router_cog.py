from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable, Optional, TypeVar

import aiohttp
import discord
from discord.ext import commands

from community_intern.ai.interfaces import AIClient
from community_intern.config.models import DiscordSettings
from community_intern.core.models import Conversation, Message, RequestContext

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class _PendingUserBatch:
    messages: list[discord.Message]
    task: asyncio.Task[None] | None
    generation: int


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
        self._pending_user_batches: dict[tuple[str, str, str], _PendingUserBatch] = {}

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
            await self._handle_channel_message(message=message)

        await self._bot.process_commands(message)

    async def _handle_channel_message(self, *, message: discord.Message) -> None:
        if message.guild is None:
            return

        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return
        if message.author is None:
            return

        if message.reference is not None and message.reference.message_id is not None:
            referenced_message = await self._resolve_referenced_message(message=message)
            if referenced_message is None:
                return
            if referenced_message.author is not None and referenced_message.author.id != message.author.id:
                return

        key = (str(message.guild.id), str(channel_id), str(message.author.id))
        self._enqueue_user_batch(message=message, key=key)
        return

    async def _resolve_referenced_message(self, *, message: discord.Message) -> Optional[discord.Message]:
        reference = message.reference
        if reference is None or reference.message_id is None:
            return None

        if isinstance(reference.resolved, discord.Message):
            return reference.resolved

        try:
            return await message.channel.fetch_message(reference.message_id)
        except discord.NotFound:
            logger.warning(
                "discord.reference_not_found platform=discord guild_id=%s channel_id=%s message_id=%s reference_id=%s",
                str(message.guild.id) if message.guild is not None else None,
                str(getattr(message.channel, "id", None)),
                str(message.id),
                str(reference.message_id),
            )
            return None
        except discord.DiscordException:
            logger.exception(
                "discord.reference_fetch_failed platform=discord guild_id=%s channel_id=%s message_id=%s reference_id=%s",
                str(message.guild.id) if message.guild is not None else None,
                str(getattr(message.channel, "id", None)),
                str(message.id),
                str(reference.message_id),
            )
            return None

    def _enqueue_user_batch(self, *, message: discord.Message, key: tuple[str, str, str]) -> None:
        pending = self._pending_user_batches.get(key)
        if pending is None:
            pending = _PendingUserBatch(messages=[], task=None, generation=0)
            self._pending_user_batches[key] = pending

        pending.messages.append(message)
        pending.generation += 1
        generation = pending.generation

        if pending.task is not None and not pending.task.done():
            pending.task.cancel()
        pending.task = asyncio.create_task(self._flush_user_batch_after_wait(key=key, generation=generation))

    async def _flush_user_batch_after_wait(self, *, key: tuple[str, str, str], generation: int) -> None:
        try:
            await asyncio.sleep(self._settings.message_batch_wait_seconds)
        except asyncio.CancelledError:
            return

        pending = self._pending_user_batches.get(key)
        if pending is None:
            return
        if pending.generation != generation:
            return

        messages = pending.messages
        if not messages:
            del self._pending_user_batches[key]
            return

        del self._pending_user_batches[key]
        try:
            await self._process_channel_batch(messages=messages)
        except Exception:
            logger.exception("discord.batch_process_failed guild_id=%s channel_id=%s author_id=%s", *key)

    async def _process_channel_batch(self, *, messages: list[discord.Message]) -> None:
        messages = [m for m in messages if (m.content or "").strip()]
        if not messages:
            return

        last_message = messages[-1]
        if last_message.guild is None:
            return

        channel_id = getattr(last_message.channel, "id", None)
        if channel_id is None:
            return

        conversation_messages: list[Message] = []
        for msg in messages:
            text = (msg.content or "").strip()
            if not text:
                continue
            conversation_messages.append(
                Message(
                    role="user",
                    text=text,
                    timestamp=_to_utc_datetime(msg.created_at),
                    author_id=str(msg.author.id) if msg.author is not None else None,
                )
            )

        if not conversation_messages:
            return

        conversation = Conversation(messages=tuple(conversation_messages))
        context = RequestContext(
            platform="discord",
            guild_id=str(last_message.guild.id),
            channel_id=str(channel_id),
            thread_id=None,
            message_id=str(last_message.id),
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

        thread_name = _thread_name_from_message(last_message.content or "")
        log_context = (
            f"platform=discord guild_id={context.guild_id} channel_id={context.channel_id} message_id={context.message_id}"
        )
        try:
            thread = await _retry_async(
                "create_thread",
                attempts=3,
                base_delay_seconds=0.5,
                make_call=lambda: last_message.create_thread(name=thread_name),
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
        if thread.owner_id is not None and thread.owner_id != bot_user_id:
            return

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
