from __future__ import annotations

from typing import Sequence

from community_intern.llm.image_adapters import Base64Image
from community_intern.core.models import ImageInput


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
