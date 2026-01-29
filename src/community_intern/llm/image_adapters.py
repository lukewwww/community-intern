from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol, Sequence, Union


@dataclass(frozen=True, slots=True)
class Base64Image:
    base64_data: str
    mime_type: str
    source_url: str
    filename: Optional[str]

    def to_data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_data}"


@dataclass(frozen=True, slots=True)
class TextPart:
    type: Literal["text"]
    text: str


@dataclass(frozen=True, slots=True)
class ImagePart:
    type: Literal["image"]
    image: Base64Image


ContentPart = Union[TextPart, ImagePart]


class LLMImageAdapter(Protocol):
    def build_user_content(self, *, parts: Sequence[ContentPart]) -> object:
        ...


@dataclass(frozen=True, slots=True)
class OpenAIImageAdapter:
    def build_user_content(self, *, parts: Sequence[ContentPart]) -> object:
        has_images = any(part.type == "image" for part in parts)
        if not has_images:
            return _collapse_text(parts)
        out: list[dict] = []
        for part in parts:
            if part.type == "text":
                out.append({"type": "text", "text": part.text})
            else:
                out.append({"type": "image_url", "image_url": {"url": part.image.to_data_url()}})
        return out


@dataclass(frozen=True, slots=True)
class GeminiImageAdapter:
    def build_user_content(self, *, parts: Sequence[ContentPart]) -> object:
        has_images = any(part.type == "image" for part in parts)
        if not has_images:
            return _collapse_text(parts)
        out: list[dict] = []
        for part in parts:
            if part.type == "text":
                out.append({"text": part.text})
            else:
                out.append(
                    {
                        "inline_data": {
                            "mime_type": part.image.mime_type,
                            "data": part.image.base64_data,
                        }
                    }
                )
        return out


@dataclass(frozen=True, slots=True)
class OpenSourceImageAdapter:
    def build_user_content(self, *, parts: Sequence[ContentPart]) -> object:
        has_images = any(part.type == "image" for part in parts)
        if not has_images:
            return _collapse_text(parts)
        out: list[dict] = []
        for part in parts:
            if part.type == "text":
                out.append({"type": "text", "text": part.text})
            else:
                out.append({"type": "image", "url": part.image.to_data_url()})
        return out


def get_image_adapter(name: str) -> LLMImageAdapter:
    if name in globals():
        cls = globals()[name]
        if isinstance(cls, type):
            return cls()
    raise ValueError(f"Unsupported image adapter: {name}")


def _collapse_text(parts: Sequence[ContentPart]) -> str:
    return "\n".join([part.text for part in parts if part.type == "text"]).strip()
