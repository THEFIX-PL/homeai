"""Situation and journal commands for the panel and cards."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
import voluptuous as vol

from .websocket import LANG, TYPE, command, lang_of, user_name


def _engine(rt: Any, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> Any:
    engine = rt.module("situations")
    if engine is None:
        connection.send_error(msg["id"], "not_loaded", "Situations are not running")
    return engine


@command({TYPE: "homeai/situations/subscribe", LANG: str})
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    """Open situations right away, then every change; plus new journal entries."""
    engine = _engine(rt, connection, msg)
    if engine is None:
        return
    lang = lang_of(rt, msg)

    @callback
    def send_all() -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"], {"type": "situations", "situations": [s.as_dict(lang) for s in engine.open()]}
            )
        )

    @callback
    def on_change(_event: str, _s: Any) -> None:
        send_all()

    @callback
    def on_journal(entry: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"type": "journal", "entry": entry}))

    unsubs = [engine.listen(on_change), rt.journal.listen(on_journal)]

    @callback
    def stop() -> None:
        for u in unsubs:
            u()

    connection.subscriptions[msg["id"]] = stop
    connection.send_result(msg["id"])
    send_all()


@command(
    {TYPE: "homeai/situations/list", LANG: str, vol.Optional("resolved", default=20): vol.All(int, vol.Range(0, 300))}
)
def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    engine = _engine(rt, connection, msg)
    if engine is None:
        return
    lang = lang_of(rt, msg)
    connection.send_result(
        msg["id"],
        {
            "open": [s.as_dict(lang) for s in engine.open()],
            "resolved": [s.as_dict(lang) for s in list(reversed(engine.resolved))[: msg["resolved"]]],
        },
    )


def _action(verb: str) -> Any:
    schema = {TYPE: f"homeai/situations/{verb}", vol.Required("situation_id"): str}
    if verb == "snooze":
        schema[vol.Optional("minutes")] = vol.All(int, vol.Range(1, 10080))

    @command(schema, is_async=True)
    async def handler(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any
    ) -> None:
        engine = _engine(rt, connection, msg)
        if engine is None:
            return
        who = user_name(hass, connection)
        if verb == "snooze":
            s = await engine.snooze(
                msg["situation_id"], msg.get("minutes") or int(rt.settings.get("notify.snooze_minutes")), who
            )
        else:
            s = await getattr(engine, {"ack": "acknowledge", "handle": "handle", "dismiss": "dismiss"}[verb])(
                msg["situation_id"], who
            )
        if s is None:
            connection.send_error(msg["id"], "not_found", "No such situation")
            return
        connection.send_result(msg["id"], {"id": s.id})

    return handler


for _verb in ("ack", "handle", "snooze", "dismiss"):
    _action(_verb)


@command(
    {
        TYPE: "homeai/journal/recent",
        vol.Optional("limit", default=100): vol.All(int, vol.Range(1, 1000)),
        vol.Optional("kind"): str,
        vol.Optional("situation_id"): str,
    }
)
def ws_journal(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(
        msg["id"],
        {"entries": rt.journal.recent(msg["limit"], kind=msg.get("kind"), situation_id=msg.get("situation_id"))},
    )
