from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from community_intern.llm.settings import LLMSettings


class AIConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # LLM Settings
    llm: LLMSettings

    # Timeouts and retries
    graph_timeout_seconds: float

    # Workflow policy
    enable_verification: bool = False

    # Prompts and policy
    project_introduction: str = ""
    gating_prompt: str
    selection_prompt: str
    answer_prompt: str
    verification_prompt: str

    # Retrieval policy
    max_sources: int

    # Output policy
    max_answer_chars: int

    # Image support
    llm_enable_image: bool = False
    llm_image_adapter: str = "OpenAIImageAdapter"
    image_download_timeout_seconds: float = 20
    image_download_max_retries: int = 2
