"""AI status for the panel: tiers, spend, what was last sent to each provider."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .websocket import TYPE, command


@command({TYPE: "homeai/ai/status"}, admin=True)
def ws_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    ai = rt.module("ai")
    if ai is None:
        connection.send_result(msg["id"], {"enabled": False})
        return
    connection.send_result(
        msg["id"],
        {
            "enabled": ai.enabled(),
            **ai.diagnostics(),
            "last_prompts": ai.last_prompts,
            "days": dict(sorted(ai.ledger.days.items())[-31:]),
        },
    )


@command({TYPE: "homeai/ai/triage", vol.Required("situation_id"): str}, admin=True, is_async=True)
async def ws_triage(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any
) -> None:
    """Run the AI assessment of a situation now."""
    ai, engine = rt.module("ai"), rt.module("situations")
    s = engine.get(msg["situation_id"]) if engine else None
    if ai is None or s is None:
        connection.send_error(msg["id"], "not_found", "No such situation or AI is not running")
        return
    if s.assessment.get("assessed_by") in ("p1", "p2", "p3"):
        s.assessment["assessed_by"] = "code"  # look again
    result = await ai.triage(s)
    connection.send_result(msg["id"], {"result": result, "assessment": s.assessment})
