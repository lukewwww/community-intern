from __future__ import annotations

from typing import Any, Mapping, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

from discord_intern.core.models import AIResult, Conversation, RequestContext


class AIClient(Protocol):
    async def generate_reply(self, conversation: Conversation, context: RequestContext) -> AIResult:
        """Return a single normalized decision + optional reply."""

    async def summarize_for_kb_index(
        self,
        *,
        source_id: str,
        text: str,
        timeout_seconds: float,
    ) -> str:
        """Return a short plain-text description for the Knowledge Base index."""


class AIConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Timeouts and retries
    request_timeout_seconds: float = 30
    llm_timeout_seconds: float = 20
    max_retries: int = 2

    # Prompts and policy
    gating_prompt: str = ""
    selection_prompt: str = ""
    summarization_prompt: str = ""
    answer_prompt: str = ""
    verification_prompt: str = ""

    # Retrieval policy
    max_sources: int = 6
    max_snippets: int = 10
    max_snippet_chars: int = 1200
    min_snippet_score: float = 0.15

    # Output policy
    max_answer_chars: int = 3000
    require_citations: bool = True


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
