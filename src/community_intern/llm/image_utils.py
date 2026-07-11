from __future__ import annotations

import io
from typing import Sequence

from PIL import Image

from community_intern.llm.image_adapters import Base64Image
from community_intern.core.models import ImageInput

_JPEG_QUALITY = 85
_MAX_SHRINK_ATTEMPTS = 8


def shrink_image_to_limit(payload: bytes, mime_type: str, *, max_bytes: int) -> tuple[bytes, str]:
    """Return the image unchanged if within max_bytes, otherwise
    downscale it proportionally and re-encode as JPEG until it fits."""
    if len(payload) <= max_bytes:
        return payload, mime_type

    with Image.open(io.BytesIO(payload)) as source:
        image = source.convert("RGB")

    width, height = image.size
    # Byte size scales roughly with pixel count, so start near the square
    # root of the target ratio and back off geometrically if needed.
    scale = (max_bytes / len(payload)) ** 0.5
    for _ in range(_MAX_SHRINK_ATTEMPTS):
        target = (max(int(width * scale), 1), max(int(height * scale), 1))
        resized = image.resize(target, Image.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            return data, "image/jpeg"
        scale *= 0.7

    raise RuntimeError(
        f"Failed to shrink image below {max_bytes} bytes after {_MAX_SHRINK_ATTEMPTS} attempts."
    )


def build_base64_images(images: Sequence[ImageInput]) -> list[Base64Image]:
    base64_images: list[Base64Image] = []
    for image in images:
        if not image.base64_data:
            raise RuntimeError(f"Missing base64 image payload. url={image.url}")
        mime_type = image.mime_type or "image/jpeg"
        base64_images.append(
            Base64Image(
                base64_data=image.base64_data,
                mime_type=mime_type,
                source_url=image.url,
                filename=image.filename,
            )
        )
    return base64_images
