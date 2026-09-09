from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


async def invoke_structured_llm(
    structured_llm: Any,
    messages: Sequence[Any],
    response_model: Type[T],
    *,
    max_attempts: int,
    step: str,
    raw_content_fallback: Optional[Callable[[str], T]] = None,
    timeout_seconds: Optional[float] = None,
) -> tuple[T, str | None]:
    """
    Invokes a structured-output LLM runnable and parses the result, retrying the
    whole step on failure up to max_attempts times.

    When raw_content_fallback is provided and the model skipped the structured
    format but returned plain text content without tool calls, the fallback
    builds the response model directly from that text instead of retrying.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        result: Any = None
        try:
            if timeout_seconds is not None:
                result = await asyncio.wait_for(
                    structured_llm.ainvoke(messages), timeout=timeout_seconds
                )
            else:
                result = await structured_llm.ainvoke(messages)
            return parse_structured_llm_result(result, response_model)
        except Exception as exc:
            if raw_content_fallback is not None and isinstance(result, dict):
                raw = result.get("raw")
                content = extract_plain_text_content(raw)
                if content is not None:
                    logger.warning(
                        "Structured LLM output is missing but the raw response has plain text "
                        "content. Using the raw content as the result. step=%s attempt=%d/%d",
                        step,
                        attempt,
                        max_attempts,
                    )
                    return raw_content_fallback(content), extract_response_id(raw)
            last_error = exc
            if attempt < max_attempts:
                logger.warning(
                    "Structured LLM step failed and will be retried. step=%s attempt=%d/%d error=%s",
                    step,
                    attempt,
                    max_attempts,
                    exc,
                )
    assert last_error is not None
    raise last_error


def parse_structured_llm_result(
    result: Any,
    response_model: Type[T],
) -> tuple[T, str | None]:
    if isinstance(result, dict) and "parsed" in result:
        parsing_error = result.get("parsing_error")
        if parsing_error is not None:
            raise RuntimeError("LLM returned unexpected structured output.") from parsing_error
        parsed = _validate_structured_output(result.get("parsed"), response_model)
        return parsed, extract_response_id(result.get("raw"))

    return _validate_structured_output(result, response_model), None


def extract_response_id(raw_response: Any) -> str | None:
    response_metadata = getattr(raw_response, "response_metadata", None)
    if not isinstance(response_metadata, dict):
        return None

    response_id = response_metadata.get("id")
    if not isinstance(response_id, str):
        return None

    response_id = response_id.strip()
    return response_id or None


def extract_plain_text_content(raw_response: Any) -> str | None:
    """
    Returns the message text when the response is a plain assistant message
    with non-empty content and no tool calls, otherwise None.
    """
    if raw_response is None:
        return None
    if getattr(raw_response, "tool_calls", None):
        return None

    content = getattr(raw_response, "content", None)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
            if not isinstance(block, dict) or block.get("type") in (None, "text")
        )
    else:
        return None

    text = text.strip()
    return text or None


def _validate_structured_output(value: Any, response_model: Type[T]) -> T:
    if value is None:
        raise RuntimeError("LLM returned null structured output.")

    if isinstance(value, response_model):
        return value

    try:
        return response_model.model_validate(value)
    except Exception as exc:
        expected = response_model.__name__
        actual = type(value).__name__
        raise RuntimeError(
            f"LLM returned unexpected structured output. expected={expected} got={actual}"
        ) from exc
