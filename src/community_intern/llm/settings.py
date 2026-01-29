from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class LLMSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    api_key: str
    model: str
    vram_limit: Optional[int] = None
    structured_output_method: Literal["json_schema", "function_calling"] = "function_calling"
    timeout_seconds: float
    max_retries: int
