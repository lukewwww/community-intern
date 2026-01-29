from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LLMTextResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
