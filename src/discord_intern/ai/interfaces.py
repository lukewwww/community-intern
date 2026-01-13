from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, TypeVar

from discord_intern.core.models import AIResult, Conversation, RequestContext


class AIClient(Protocol):
    async def generate_reply(self, conversation: Conversation, context: RequestContext) -> AIResult:
        """Return a single normalized decision + optional reply."""


@dataclass(frozen=True, slots=True)
class AIConfig:
    # Timeouts and retries
    request_timeout_seconds: float
    llm_timeout_seconds: float
    max_retries: int

    # Prompts and policy
    gating_prompt: str
    answer_prompt: str
    verification_prompt: str

    # Retrieval policy
    max_sources: int
    max_snippets: int
    max_snippet_chars: int
    min_snippet_score: float

    # Output policy
    max_answer_chars: int
    require_citations: bool


T = TypeVar("T")


class LLMClient(Protocol):
    async def complete_text(self, *, prompt: str, timeout_seconds: float) -> str:
        """Return plain text output."""

    async def complete_json(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Return structured JSON output matching the provided schema."""

