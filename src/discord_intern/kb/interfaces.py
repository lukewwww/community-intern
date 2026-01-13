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
    tags: Sequence[str] = ()
    summary: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class Snippet:
    source_id: str
    text: str
    score: float


class KnowledgeBase(Protocol):
    async def load_index(self) -> Sequence[Source]:
        """Load the startup-produced index artifact into memory."""

    async def build_index(self) -> None:
        """Build the startup index artifact on disk."""

    async def select_sources(self, *, query: str, max_sources: int) -> Sequence[Source]:
        """Select sources using an index-first routing strategy."""

    async def retrieve_snippets(
        self,
        *,
        query: str,
        sources: Sequence[Source],
        max_snippets: int,
        max_snippet_chars: int,
    ) -> Sequence[Snippet]:
        """Return bounded, ranked snippets for grounding and citation."""

