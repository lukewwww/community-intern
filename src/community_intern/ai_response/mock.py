from __future__ import annotations

from dataclasses import dataclass

from community_intern.core.models import AIResult, Conversation, RequestContext
@dataclass(frozen=True, slots=True)
class MockAIResponseService:
    """
    A deterministic AI response service for end-to-end adapter testing.

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
            debug={
                "mock": True,
                "message_count": len(conversation.messages),
                "platform": context.platform,
            },
        )
