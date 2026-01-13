from __future__ import annotations

from typing import Optional, Sequence, TypedDict


class Snippet(TypedDict):
    source_id: str
    text: str
    score: float


class GateDecision(TypedDict):
    is_question: bool
    is_answerable: bool
    rewrite_query: Optional[str]
    reason: str


class VerificationResult(TypedDict):
    is_good_enough: bool
    issues: Sequence[str]
    suggested_fix: Optional[str]


class GraphState(TypedDict):
    """
    Conceptual LangGraph state shape.

    This is a contract for orchestration state, not an implementation.
    """

    # Inputs (types live in discord_intern.core.models and discord_intern.ai.interfaces)
    conversation: object
    context: object
    config: object

    # Derived
    user_question: str
    gate: GateDecision

    # Retrieval
    query: str
    snippets: Sequence[Snippet]
    used_sources: Sequence[str]

    # Generation
    draft_answer: str
    citations: Sequence[object]

    # Verification
    verification: VerificationResult

