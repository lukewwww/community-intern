from __future__ import annotations

import asyncio
from typing import Optional, Sequence, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_crynux import ChatCrynux
from pydantic import BaseModel

from community_intern.llm.image_adapters import ImagePart, TextPart, get_image_adapter
from community_intern.core.models import ImageInput
from community_intern.llm.image_utils import build_base64_images
from community_intern.llm.settings import LLMSettings

T = TypeVar("T", bound=BaseModel)


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
            **({"vram_limit": llm.vram_limit} if llm.vram_limit is not None else {}),
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
        )
        result = await asyncio.wait_for(
            structured_llm.ainvoke(messages),
            timeout=self._llm_config.timeout_seconds,
        )
        if result is None:
            raise RuntimeError("LLM returned null structured output.")
        try:
            return response_model.model_validate(result)
        except Exception as exc:
            raise RuntimeError(
                f"LLM returned unexpected structured output. expected={response_model.__name__} got={type(result).__name__}"
            ) from exc
