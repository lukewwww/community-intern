from __future__ import annotations

from typing import Any, Mapping, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

from community_intern.core.models import AIResult, Conversation, RequestContext


class AIClient(Protocol):
    async def generate_reply(self, conversation: Conversation, context: RequestContext) -> AIResult:
        """Return a single normalized decision + optional reply."""

    async def summarize_for_kb_index(
        self,
        *,
        source_id: str,
        text: str,
    ) -> str:
        """Return a short plain-text description for the Knowledge Base index."""


class AIConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # LLM Settings
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    # Timeouts and retries
    graph_timeout_seconds: float
    llm_timeout_seconds: float
    max_retries: int

    # Workflow policy
    enable_verification: bool = False

    # Prompts and policy
    project_introduction: str = ""
    gating_prompt: str
    selection_prompt: str
    summarization_prompt: str
    answer_prompt: str
    verification_prompt: str

    # Retrieval policy
    max_sources: int
    max_snippets: int
    max_snippet_chars: int
    min_snippet_score: float

    # Output policy
    max_answer_chars: int
