"""Custom detectors: rules without code, validated, evaluated and editable over WebSocket."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest

from custom_components.homeai.settings import SettingError
from custom_components.homeai.signals.detectors.custom import validate_rules

from .common import settle, setup_homeai
from .home import standard_home

FREEZER = {
    "id": "freezer",
    "name": "Freezer too warm",
    "target": {"entities": ["sensor.freezer"]},
    "condition": {"type": "above", "value": -10},
    "minutes": 15,
    "severity": 3,
    "category": "damage",
    "advice": "Check that the door is closed.",
}


def test_validation() -> None:
    [rule] = validate_rules([FREEZER])
    assert rule["mode"] == "each" and rule["when"] == "always" and rule["need"] == "member"
    for bad, reason in (
        ({**FREEZER, "id": "Bad Id"}, "id"),
        ({**FREEZER, "target": {}}, "target"),
        ({**FREEZER, "condition": {"type": "above", "value": "warm"}}, "number"),
        ({**FREEZER, "severity": 7}, "severity"),
        ({**FREEZER, "category": "fun"}, "category"),
    ):
        with pytest.raises(SettingError, match=reason):
            validate_rules([bad])
    with pytest.raises(SettingError, match="unique"):
        validate_rules([FREEZER, FREEZER])


async def test_rule_opens_a_situation_after_its_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    home.entity(
        "sensor.freezer", "-18", area="Kitchen", attrs={"unit_of_measurement": "°C", "friendly_name": "Freezer"}
    )
    rt = await setup_homeai(hass, {"detectors.custom": [FREEZER]})
    hub = rt.module("signals")
    home.set("sensor.freezer", "-5")
    assert not [s for s in hub.evaluate().values() if s and s.kind == "custom"]
    freezer.tick(timedelta(minutes=16))
    await settle(hass, rt)
    [s] = rt.module("situations").open()
    assert s.kind == "custom" and s.severity == 3 and s.category == "damage"
    assert s.title("en") == "Freezer too warm: Freezer" and s.description("en") == "Check that the door is closed."


async def test_label_targets_and_all_mode(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    label = home.label("Plants")
    home.entity("sensor.fern", "10", labels=("Plants",))
    home.entity("sensor.cactus", "40", labels=("Plants",))
    each = {
        "id": "dry",
        "name": "Plant dry",
        "target": {"label": label},
        "condition": {"type": "below", "value": 20},
        "minutes": 0,
        "severity": 1,
        "category": "maintenance",
    }
    every = {**each, "id": "all_dry", "name": "All plants dry", "mode": "all"}
    rt = await setup_homeai(hass, {"detectors.custom": [each, every]})
    found = [s for s in rt.module("signals").evaluate().values() if s and s.kind == "custom"]
    assert [s.entities for s in found] == [("sensor.fern",)]
    home.set("sensor.cactus", "5")
    found = {s.id for s in rt.module("signals").evaluate().values() if s and s.kind == "custom"}
    assert "custom:all_dry:all" in found and "custom:dry:sensor.cactus" in found


async def test_only_when_away(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rule = {
        "id": "tv",
        "name": "TV on in an empty home",
        "target": {"entities": ["switch.coffee"]},
        "condition": {"type": "state", "value": "on"},
        "when": "away",
        "severity": 1,
        "category": "energy",
    }
    rt = await setup_homeai(hass, {"detectors.custom": [rule]})
    home.set("switch.coffee", "on")
    hub = rt.module("signals")
    hub.evaluate()
    assert not [s for s in hub.signals.values() if s.kind == "custom"]
    home.set("person.anna", "not_home")
    hub.evaluate()
    assert [s for s in hub.signals.values() if s.kind == "custom"]


async def test_rules_websocket(hass: HomeAssistant, hass_ws_client) -> None:
    home = standard_home(hass)
    home.entity("sensor.freezer", "-5", area="Kitchen")
    rt = await setup_homeai(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/rules/preview", "rule": FREEZER})
    msg = await client.receive_json()
    assert msg["result"]["covered"][0]["entity_id"] == "sensor.freezer" and msg["result"]["meeting"] == [
        "sensor.freezer"
    ]
    await client.send_json_auto_id({"type": "homeai/rules/save", "rules": [FREEZER]})
    msg = await client.receive_json()
    assert msg["success"] and rt.settings.get("detectors.custom")[0]["id"] == "freezer"
    await client.send_json_auto_id({"type": "homeai/rules/save", "rules": [{**FREEZER, "severity": 9}]})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "invalid_format"
    await client.send_json_auto_id({"type": "homeai/rules/list"})
    msg = await client.receive_json()
    assert msg["result"]["rules"][0]["firing"] is False
