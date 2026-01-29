from __future__ import annotations

from typing import Sequence, TypedDict


class GraphState(TypedDict):
    """
    Conceptual LangGraph state shape.

    This is a contract for orchestration state, not an implementation.
    """

    # Inputs (types live in community_intern.core.models and community_intern.ai_response.config)
    conversation: object
    context: object
    config: object

    # Derived
    user_question: str
    selected_source_ids: Sequence[str]
    loaded_sources: Sequence[object]

    # Generation
    draft_answer: str

    # Verification
    verification: bool
