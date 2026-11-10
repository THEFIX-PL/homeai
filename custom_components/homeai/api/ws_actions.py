"""Actions, approvals, the plan and presence exceptions for the panel and cards."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
import voluptuous as vol

from ..policy import ActionRequest
from ..schedule.scheduler import PlanError
from .websocket import TYPE, command

Conn = websocket_api.ActiveConnection


def _module(rt: Any, connection: Conn, msg: dict[str, Any], name: str) -> Any:
    module = rt.module(name)
    if module is None:
        connection.send_error(msg["id"], "not_loaded", f"{name} is not running")
    return module


# ——— Actions ———
@command({TYPE: "homeai/actions/recent", vol.Optional("limit", default=30): vol.All(int, vol.Range(1, 100))})
def ws_recent(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (executor := _module(rt, connection, msg, "executor")) is not None:
        connection.send_result(msg["id"], {"actions": list(executor.recent)[: msg["limit"]]})


@command(
    {
        TYPE: "homeai/actions/execute",
        vol.Required("service"): str,
        vol.Optional("entity_ids", default=[]): [str],
        vol.Optional("data", default={}): dict,
        vol.Optional("confirmed", default=False): bool,
        vol.Optional("dry_run", default=False): bool,
    },
    is_async=True,
)
async def ws_execute(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    """A person runs an action through the policy in their own context."""
    if (executor := _module(rt, connection, msg, "executor")) is None:
        return
    domain, _, service = msg["service"].partition(".")
    result = await executor.execute(
        ActionRequest(
            domain,
            service,
            msg["data"],
            entity_ids=msg["entity_ids"],
            actor="person",
            user_id=connection.user.id,
            confirmed=msg["confirmed"],
            dry_run=msg["dry_run"],
            reason="panel",
        )
    )
    connection.send_result(msg["id"], result.as_dict())


@command({TYPE: "homeai/actions/undo", vol.Required("action_id"): str}, is_async=True)
async def ws_undo(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (executor := _module(rt, connection, msg, "executor")) is not None:
        connection.send_result(msg["id"], (await executor.undo(msg["action_id"], connection.user.id)).as_dict())


# ——— Approvals ———
@command({TYPE: "homeai/approvals/list"})
def ws_approvals(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (approvals := _module(rt, connection, msg, "approvals")) is not None:
        recent = sorted(approvals.items.values(), key=lambda a: a["created"], reverse=True)[:30]
        connection.send_result(msg["id"], {"pending": approvals.pending(), "recent": recent})


@command({TYPE: "homeai/approvals/subscribe"})
def ws_approvals_subscribe(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (approvals := _module(rt, connection, msg, "approvals")) is None:
        return

    @callback
    def changed(_item: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"pending": approvals.pending()}))

    connection.subscriptions[msg["id"]] = approvals.listen(changed)
    connection.send_result(msg["id"])
    changed({})


def _decide(verb: str) -> None:
    @command({TYPE: f"homeai/approvals/{verb}", vol.Required("approval_id"): str}, is_async=True)
    async def handler(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
        if (approvals := _module(rt, connection, msg, "approvals")) is None:
            return
        item = await getattr(approvals, verb)(msg["approval_id"], connection.user.id)
        if item is None:
            connection.send_error(msg["id"], "unauthorized", "Not allowed or no longer pending")
            return
        connection.send_result(msg["id"], item)


_decide("approve")
_decide("deny")


# ——— Plan ———
@command({TYPE: "homeai/plan/list", vol.Optional("days", default=14): vol.All(int, vol.Range(1, 366))})
def ws_plan(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (scheduler := _module(rt, connection, msg, "scheduler")) is None:
        return
    now = dt_util.utcnow()
    occurrences = [
        {"at": t.isoformat(timespec="seconds"), "entry_id": e["id"], "title": e["title"]}
        for t, e in scheduler.occurrences(now, now + timedelta(days=msg["days"]))
    ]
    connection.send_result(msg["id"], {"entries": list(scheduler.entries.values()), "occurrences": occurrences})


@command({TYPE: "homeai/plan/save", vol.Optional("entry_id"): str, vol.Required("entry"): dict}, is_async=True)
async def ws_plan_save(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (scheduler := _module(rt, connection, msg, "scheduler")) is None:
        return
    try:
        entry = await scheduler.save(msg["entry"], connection.user.id, msg.get("entry_id"))
    except PlanError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], entry)


@command({TYPE: "homeai/plan/delete", vol.Required("entry_id"): str}, is_async=True)
async def ws_plan_delete(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (scheduler := _module(rt, connection, msg, "scheduler")) is None:
        return
    try:
        removed = await scheduler.remove(msg["entry_id"], connection.user.id)
    except PlanError as err:
        connection.send_error(msg["id"], "unauthorized", str(err))
        return
    connection.send_result(msg["id"], {"removed": removed})


# ——— Presence exceptions ———
@command({TYPE: "homeai/presence/list", vol.Optional("days", default=60): vol.All(int, vol.Range(1, 366))})
def ws_presence(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (module := _module(rt, connection, msg, "presence_exceptions")) is None:
        return
    now = dt_util.utcnow()
    connection.send_result(
        msg["id"], {"items": module.between(now - timedelta(days=1), now + timedelta(days=msg["days"]))}
    )


@command({TYPE: "homeai/presence/save", vol.Optional("exception_id"): str, vol.Required("item"): dict})
def ws_presence_save(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (module := _module(rt, connection, msg, "presence_exceptions")) is None:
        return
    try:
        item = module.save(msg["item"], msg.get("exception_id"), author=connection.user.id)
    except (ValueError, KeyError) as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], item)


@command({TYPE: "homeai/presence/delete", vol.Required("exception_id"): str})
def ws_presence_delete(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    if (module := _module(rt, connection, msg, "presence_exceptions")) is not None:
        connection.send_result(msg["id"], {"removed": module.remove(msg["exception_id"])})
