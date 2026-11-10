"""Conversation agent `conversation.homeai`: talk to HomeAI from Assist, voice satellites or the app."""

from __future__ import annotations

from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.components.conversation import AssistantContent, ChatLog, ConversationEntity, ConversationInput
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HomeAIEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([HomeAIConversation(entry.runtime_data)])


class HomeAIConversation(HomeAIEntity, ConversationEntity):
    platform_domain = "conversation"

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "assistant")
        self.entity_id = "conversation.homeai"

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return "*"

    async def _async_handle_message(
        self, user_input: ConversationInput, chat_log: ChatLog
    ) -> conversation.ConversationResult:
        ai = self.rt.module("ai")
        if ai is not None and (ai.available("p1") or ai.available("p2")):
            reply, _actions = await ai.chat(user_input.text, chat_log.conversation_id, user_input.context.user_id)
        else:
            reply = self._without_ai()
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(agent_id=user_input.agent_id, content=reply)
        )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    def _without_ai(self) -> str:
        """No AI tier: a plain summary of what is open."""
        engine = self.rt.module("situations")
        items = [s for s in engine.open() if s.severity >= 1] if engine else []
        if not items:
            return self.rt.text("ai|all_quiet")
        titles = [s.title(self.rt.language) for s in items[:5]]
        return self.rt.text("ai|open_summary", count=len(items), titles=titles)
