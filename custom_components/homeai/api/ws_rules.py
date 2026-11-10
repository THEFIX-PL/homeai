"""Custom detectors (rules without code) for the panel: list, save, preview."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import voluptuous as vol

from ..settings import SettingError
from ..signals.detectors.custom import meets, targets, validate_rules
from .websocket import TYPE, command, user_name

Conn = websocket_api.ActiveConnection


@command({TYPE: "homeai/rules/list"}, admin=True)
def ws_list(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    hub = rt.module("signals")
    active = {s.data.get("rule"): s for s in hub.signals.values() if s.kind == "custom"} if hub else {}
    connection.send_result(
        msg["id"],
        {"rules": [{**r, "firing": r["id"] in active} for r in rt.settings.get("detectors.custom") or []]},
    )


@command({TYPE: "homeai/rules/save", vol.Required("rules"): list}, admin=True)
def ws_save(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    rules = rt.settings.set(
        "detectors.custom", msg["rules"], user=user_name(hass, connection), confirmed=True, is_admin=True
    )
    rt.journal.add(
        "setting", rt.text("journal|setting_changed", key="detectors.custom"), actor=user_name(hass, connection)
    )
    connection.send_result(msg["id"], {"rules": rules})


@command({TYPE: "homeai/rules/preview", vol.Required("rule"): dict}, admin=True)
def ws_preview(hass: HomeAssistant, connection: Conn, msg: dict[str, Any], rt: Any) -> None:
    """Which entities the rule covers and which meet its condition right now (ignoring the waiting time)."""
    try:
        [rule] = validate_rules([msg["rule"]])
    except SettingError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    ctx = rt.module("signals").context()
    covered = targets(ctx, rule)
    now = {**rule, "minutes": 0}
    meeting = [e for e in covered if meets(replace(ctx), now, e)]
    connection.send_result(
        msg["id"],
        {
            "covered": [{"entity_id": e, "name": rt.world.display_name(e)} for e in covered[:200]],
            "meeting": meeting[:200],
        },
    )
