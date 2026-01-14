from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Sequence

Role = Literal["user", "assistant", "system"]
Platform = Literal["discord"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    text: str
    timestamp: datetime
    author_id: Optional[str]


@dataclass(frozen=True, slots=True)
class Conversation:
    messages: Sequence[Message]


@dataclass(frozen=True, slots=True)
class RequestContext:
    platform: Platform
    channel_id: str
    message_id: str
    thread_id: Optional[str]
    guild_id: Optional[str]


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: str
    quote: Optional[str] = None


@dataclass(frozen=True, slots=True)
class AIResult:
    should_reply: bool
    reply_text: Optional[str]
    citations: Sequence[Citation] = ()
    debug: Optional[dict] = None




