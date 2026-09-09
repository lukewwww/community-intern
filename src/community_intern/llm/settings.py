from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LLMSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    api_key: str
    model: str
    vram_limit: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    structured_output_method: Literal["json_schema", "function_calling"] = "function_calling"
    structured_output_max_attempts: int = Field(default=2, ge=1)
    use_responses_api: bool = True
    background: bool = True
    http_timeout_seconds: float = 3
    poll_interval: float = 10.0
    timeout_seconds: float
    max_retries: int

    def chat_crynux_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "use_responses_api": self.use_responses_api,
            "background": self.background,
            "http_timeout": self.http_timeout_seconds,
            "poll_interval": self.poll_interval,
        }
        if self.vram_limit is not None:
            kwargs["vram_limit"] = self.vram_limit
        if self.max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = self.max_completion_tokens
        return kwargs
