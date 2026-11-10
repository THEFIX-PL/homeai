"""Learning and memory for the panel: proposals, facts, the weekly review."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .websocket import TYPE, command

Conn = websocket_api.ActiveConnection


@command({TYPE: "homeai/learning/status"})
def ws_status(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    learning, memory = rt.module("learning"), rt.module("memory")
    connection.send_result(
        msg["id"],
        {
            "proposals": [p for p in learning.proposals.values() if p["status"] == "pending"] if learning else [],
            "reviews": list(reversed(learning.reviews)) if learning else [],
            "norms": len(learning.baselines.norms) if learning else 0,
            "facts": sorted(memory.facts.values(), key=lambda f: f["created"], reverse=True)[:200] if memory else [],
        },
    )


@command({TYPE: "homeai/learning/approve", vol.Required("proposal_id"): str}, is_async=True)
async def ws_approve(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    proposal = await rt.module("learning").approve(msg["proposal_id"], connection.user.id)
    if proposal is None:
        connection.send_error(msg["id"], "not_found", "No such pending proposal")
        return
    connection.send_result(msg["id"], proposal)


@command({TYPE: "homeai/learning/reject", vol.Required("proposal_id"): str})
def ws_reject(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], {"rejected": rt.module("learning").reject(msg["proposal_id"])})


@command({TYPE: "homeai/learning/review"}, admin=True, is_async=True)
async def ws_review(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], await rt.module("learning").weekly_review())


@command({TYPE: "homeai/memory/add", vol.Required("text"): str, vol.Optional("scope", default="home"): str})
def ws_memory_add(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    fact = rt.module("memory").add(msg["text"], scope=msg["scope"], source="person", author=connection.user.id)
    connection.send_result(msg["id"], fact)


@command({TYPE: "homeai/memory/approve", vol.Required("fact_id"): str})
def ws_memory_approve(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], {"approved": rt.module("memory").approve(msg["fact_id"])})


@command({TYPE: "homeai/memory/remove", vol.Required("fact_id"): str})
def ws_memory_remove(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], {"removed": rt.module("memory").remove(msg["fact_id"])})
