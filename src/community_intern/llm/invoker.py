from __future__ import annotations

import logging
import time
from typing import Optional, Sequence, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_crynux import ChatCrynux
from pydantic import BaseModel

from community_intern.llm.image_adapters import ImagePart, TextPart, get_image_adapter
from community_intern.core.models import ImageInput
from community_intern.llm.image_utils import build_base64_images
from community_intern.llm.settings import LLMSettings
from community_intern.llm.structured_output import invoke_structured_llm
from community_intern.logging.flow import format_llm_flow_log, format_text_preview, text_chars

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class LLMInvoker:
    def __init__(
        self,
        *,
        llm: LLMSettings,
        project_introduction: str = "",
        llm_enable_image: bool = False,
        llm_image_adapter: str = "openai",
    ) -> None:
        self._llm_config = llm
        self._project_introduction = project_introduction
        self._llm_enable_image = llm_enable_image
        self._image_adapter = get_image_adapter(llm_image_adapter)

        self._llm = ChatCrynux(
            base_url=llm.base_url,
            api_key=llm.api_key,
            model=llm.model,
            **llm.chat_crynux_kwargs(),
            temperature=0.0,
            request_timeout=llm.timeout_seconds,
            max_retries=llm.max_retries,
        )

    @property
    def project_introduction(self) -> str:
        return self._project_introduction

    async def invoke_llm(
        self,
        *,
        system_prompt: str,
        user_content: str,
        images: Optional[Sequence[ImageInput]] = None,
        response_model: Type[T],
    ) -> T:
        image_count = len(images) if images else 0
        if images:
            if not self._llm_enable_image:
                raise RuntimeError("Image input is disabled by configuration.")
            base64_images = build_base64_images(images)
            user_message = HumanMessage(
                content=self._image_adapter.build_user_content(
                    parts=[
                        TextPart(type="text", text=user_content),
                        *[ImagePart(type="image", image=img) for img in base64_images],
                    ]
                )
            )
        else:
            user_message = HumanMessage(content=user_content)

        messages = [
            SystemMessage(content=system_prompt),
            user_message,
        ]

        structured_llm = self._llm.with_structured_output(
            response_model,
            method=self._llm_config.structured_output_method,
            include_raw=True,
        )
        started = time.perf_counter()
        logger.info(
            "%s",
            format_llm_flow_log(
                fields=[
                    ("Event", "Generic structured LLM request is starting"),
                    ("Response model", response_model.__name__),
                    ("Model", self._llm_config.model),
                    ("Has images", image_count > 0),
                    ("Image count", image_count),
                    ("System prompt characters", text_chars(system_prompt)),
                    ("User content characters", text_chars(user_content)),
                    ("User content", format_text_preview(user_content)),
                    ("Timeout seconds", self._llm_config.timeout_seconds),
                ]
            ),
        )
        validated, response_id = await invoke_structured_llm(
            structured_llm,
            messages,
            response_model,
            max_attempts=self._llm_config.structured_output_max_attempts,
            step=f"invoker:{response_model.__name__}",
            timeout_seconds=self._llm_config.timeout_seconds,
        )

        logger.info(
            "%s",
            format_llm_flow_log(
                fields=[
                    ("Event", "Generic structured LLM result has been received"),
                    ("Response model", response_model.__name__),
                    ("Model", self._llm_config.model),
                    ("ID", response_id),
                    ("Result type", type(validated).__name__),
                    (
                        "Elapsed milliseconds",
                        int((time.perf_counter() - started) * 1000),
                    ),
                ]
            ),
        )
        return validated
