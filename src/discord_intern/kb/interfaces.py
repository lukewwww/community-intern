from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol, Sequence

SourceType = Literal["file", "url"]


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    type: SourceType
    path: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """
    One entry in the startup index artifact.

    The index artifact is a plain text file where each entry starts with a source identifier
    (file path or URL) followed by a short free-text description.
    """

    source_id: str
    description: str


@dataclass(frozen=True, slots=True)
class SourceContent:
    source_id: str
    text: str


class KnowledgeBase(Protocol):
    async def load_index_text(self) -> str:
        """Load the startup-produced index artifact as plain text."""

    async def load_index_entries(self) -> Sequence[IndexEntry]:
        """Load the startup-produced index artifact as structured entries."""

    async def build_index(self) -> None:
        """Build the startup index artifact on disk."""

    async def load_source_content(self, *, source_id: str) -> SourceContent:
        """Load full source content for a file path or URL identifier."""
