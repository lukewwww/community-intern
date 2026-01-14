from __future__ import annotations

from dataclasses import dataclass

from community_intern.core.models import AIResult, Conversation, RequestContext


@dataclass(frozen=True, slots=True)
class MockAIClient:
    """
    A deterministic AI client for end-to-end adapter testing.

    For any input conversation, returns a fixed reply text.
    """

    reply_text: str = (
        "Mock AI response: thanks for your message. "
        "This is a fixed reply used to test the Discord adapter end-to-end."
    )

    async def generate_reply(self, conversation: Conversation, context: RequestContext) -> AIResult:
        return AIResult(
            should_reply=True,
            reply_text=self.reply_text,
            citations=(),
            debug={
                "mock": True,
                "message_count": len(conversation.messages),
                "platform": context.platform,
            },
        )

    async def summarize_for_kb_index(
        self,
        *,
        source_id: str,
        text: str,
        timeout_seconds: float,
    ) -> str:
        """Return a short plain-text description for the Knowledge Base index."""
        return f"Mock summary for {source_id}: {text[:50]}..."



