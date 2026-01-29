from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional, Sequence

import aiohttp

from community_intern.core.models import ImageInput
from community_intern.llm.image_adapters import Base64Image

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_ERRORS: tuple[type[BaseException], ...] = (
    aiohttp.ClientConnectorError,
    aiohttp.ClientOSError,
    aiohttp.ServerDisconnectedError,
    asyncio.TimeoutError,
    ConnectionResetError,
)


class ImageDownloadError(RuntimeError):
    pass


def _resolve_mime_type(*, response_type: Optional[str], fallback: Optional[str]) -> str:
    if response_type:
        return response_type.split(";")[0].strip()
    if fallback:
        return fallback
    return "image/jpeg"


async def _download_one(
    session: aiohttp.ClientSession,
    image: ImageInput,
    *,
    timeout_seconds: float,
    max_retries: int,
) -> Base64Image:
    last_error: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(image.url, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise ImageDownloadError(
                        f"Image download failed with status {response.status}. url={image.url}"
                    )
                content_type = response.headers.get("Content-Type")
                payload = await response.read()
                if not payload:
                    raise ImageDownloadError(f"Image download returned empty content. url={image.url}")
                mime_type = _resolve_mime_type(response_type=content_type, fallback=image.mime_type)
                encoded = base64.b64encode(payload).decode("ascii")
                return Base64Image(
                    base64_data=encoded,
                    mime_type=mime_type,
                    source_url=image.url,
                    filename=image.filename,
                )
        except _RETRYABLE_HTTP_ERRORS as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            delay_seconds = 0.5 * (2 ** (attempt - 1))
            logger.warning(
                "Retrying image download. attempt=%s/%s delay_seconds=%s url=%s error=%s",
                attempt,
                max_retries,
                delay_seconds,
                image.url,
                type(exc).__name__,
            )
            await asyncio.sleep(delay_seconds)
        except ImageDownloadError:
            raise
        except Exception as exc:
            logger.exception("Unexpected image download error. url=%s", image.url)
            raise ImageDownloadError(f"Image download failed. url={image.url}") from exc

    raise ImageDownloadError(
        f"Image download failed after retries. url={image.url} error={type(last_error).__name__ if last_error else 'unknown'}"
    )


async def download_images_as_base64(
    images: Sequence[ImageInput],
    *,
    timeout_seconds: float,
    max_retries: int,
) -> list[Base64Image]:
    if not images:
        return []
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results: list[Base64Image] = []
        for image in images:
            try:
                results.append(
                    await _download_one(
                        session,
                        image,
                        timeout_seconds=timeout_seconds,
                        max_retries=max_retries,
                    )
                )
            except Exception:
                logger.exception("Image download failed. url=%s", image.url)
                raise
        return results
