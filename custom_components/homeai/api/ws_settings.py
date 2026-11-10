"""Settings commands: schema for the generated settings panel, read, write, reset, undo, history, import/export."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import voluptuous as vol

from .. import i18n
from ..settings import SettingError, parse_scope_key
from .websocket import LANG, SCOPE, TYPE, command, lang_of, scope_from, user_name


def describe_settings(rt: Any, lang: str) -> dict[str, Any]:
    """Sections and settings with labels, current values and overrides — everything the panel renders."""
    settings = rt.settings
    labels = i18n.section(lang, "settings")
    option_labels = i18n.section(lang, "options")
    sections = i18n.section(lang, "sections")
    items = []
    for s in settings.registry:
        item = s.describe()
        text = labels.get(s.key) or {}
        item["label"] = text.get("label", s.key)
        item["description"] = text.get("description", "")
        item["value"] = settings.get(s.key)
        item["source"] = settings.source(s.key)
        item["overrides"] = settings.overrides_of(s.key)
        if s.options:
            names = option_labels.get(s.key) or {}
            item["option_labels"] = {o: names.get(o, o) for o in s.options}
        items.append(item)
    return {
        "language": lang,
        "sections": [
            {
                "id": sid,
                "label": (sections.get(sid) or {}).get("label", sid),
                "description": (sections.get(sid) or {}).get("description", ""),
            }
            for sid in settings.registry.sections()
        ],
        "settings": items,
    }


@command({TYPE: "homeai/settings/schema", LANG: str}, admin=True)
def ws_schema(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], describe_settings(rt, lang_of(rt, msg)))


@command({TYPE: "homeai/settings/scope", vol.Required("scope"): str}, admin=True)
def ws_scope(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    """Overrides stored for one entity, device, area, floor or person."""
    skey = scope_from(msg)
    connection.send_result(msg["id"], {"scope": skey, "values": rt.settings.overrides_for(skey)})


@command(
    {
        TYPE: "homeai/settings/set",
        vol.Required("key"): str,
        vol.Required("value"): object,
        SCOPE: str,
        vol.Optional("confirmed", default=False): bool,
    },
    admin=True,
)
def ws_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    skey = scope_from(msg)
    if not msg["confirmed"] and rt.settings.needs_confirmation(msg["key"], msg["value"], skey):
        connection.send_result(msg["id"], {"needs_confirmation": True})
        return
    value = rt.settings.set(
        msg["key"],
        msg["value"],
        skey=skey,
        user=user_name(hass, connection),
        confirmed=msg["confirmed"],
        is_admin=connection.user.is_admin,
    )
    rt.journal.add("setting", rt.text("journal|setting_changed", key=msg["key"]), actor=user_name(hass, connection))
    connection.send_result(msg["id"], {"value": value, "source": rt.settings.source(msg["key"])})


@command({TYPE: "homeai/settings/reset", vol.Required("key"): str, SCOPE: str}, admin=True)
def ws_reset(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    rt.settings.reset(msg["key"], skey=scope_from(msg), user=user_name(hass, connection))
    connection.send_result(msg["id"], {"value": rt.settings.get(msg["key"])})


@command({TYPE: "homeai/settings/reset_section", vol.Required("section"): str}, admin=True)
def ws_reset_section(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any
) -> None:
    if msg["section"] not in rt.settings.registry.sections():
        raise SettingError(f"Unknown section {msg['section']}")
    count = rt.settings.reset_section(msg["section"], user=user_name(hass, connection))
    connection.send_result(msg["id"], {"reset": count})


@command({TYPE: "homeai/settings/undo"}, admin=True)
def ws_undo(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], {"undone": rt.settings.undo_last(user=user_name(hass, connection))})


@command(
    {TYPE: "homeai/settings/history", vol.Optional("limit", default=100): vol.All(int, vol.Range(1, 500))}, admin=True
)
def ws_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], {"history": rt.settings.history(msg["limit"])})


@command({TYPE: "homeai/settings/export"}, admin=True)
def ws_export(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    connection.send_result(msg["id"], rt.settings.export())


@command({TYPE: "homeai/settings/import", vol.Required("data"): dict}, admin=True)
def ws_import(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    for skey in msg["data"].get("overrides") or {}:
        parse_scope_key(skey)
    count = rt.settings.import_(msg["data"], user=user_name(hass, connection))
    connection.send_result(msg["id"], {"changed": count})


@command({TYPE: "homeai/world/summary"}, admin=False)
def ws_world(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any], rt: Any) -> None:
    """Rooms, floors and people for selectors and overviews in the panel."""
    w = rt.world
    connection.send_result(
        msg["id"],
        {
            "summary": w.summary(),
            "floors": [{"id": f.floor_id, "name": f.name, "level": f.level} for f in w.floors.values()],
            "areas": [{"id": a.area_id, "name": a.name, "floor_id": a.floor_id} for a in w.areas.values()],
            "persons": [
                {
                    "id": p.entity_id,
                    "name": p.name,
                    "role": p.role,
                    "home": p.home,
                    "sleep": p.sleep.asleep,
                    "sleep_source": p.sleep.source,
                }
                for p in rt.presence.people()
            ],
            "day_part": rt.presence.day_part(),
            "house_mode": rt.presence.house_mode(),
        },
    )
