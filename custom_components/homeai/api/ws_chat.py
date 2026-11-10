"""Chat commands for the panel and the conversation card: talk to HomeAI in the person's own account."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.util import ulid as ulid_util
import voluptuous as vol

from .service_ai import answer
from .websocket import TYPE, command

Conn = websocket_api.ActiveConnection
CONVERSATION = vol.All(str, vol.Length(min=1, max=100))


@command(
    {
        TYPE: "homeai/chat/send",
        vol.Required("text"): vol.All(str, vol.Length(min=1, max=2000)),
        vol.Optional("conversation_id"): CONVERSATION,
    },
    is_async=True,
)
async def ws_send(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    conversation = msg.get("conversation_id") or f"panel-{ulid_util.ulid_now().lower()}"
    result = await answer(rt, msg["text"].strip(), conversation, connection.user.id)
    connection.send_result(msg["id"], {**result, "conversation_id": conversation})


@command({TYPE: "homeai/chat/history", vol.Required("conversation_id"): CONVERSATION})
def ws_history(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    from ..ai.missions.chat import history

    ai = rt.module("ai")
    log = history(ai, msg["conversation_id"], connection.user.id) if ai is not None else []
    connection.send_result(msg["id"], {"conversation_id": msg["conversation_id"], "messages": log})
