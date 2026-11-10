"""Services, situation WebSocket commands and HomeAI's own entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.homeai.const import DOMAIN

from .common import setup_homeai
from .home import standard_home


async def report(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call(DOMAIN, "report_signal", data, blocking=True, return_response=True)


async def test_report_and_clear_signal(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    result = await report(hass, id="filter", title="Clean the washer filter", severity=2, category="maintenance")
    assert result == {"signal_id": "external:service:filter"}
    await hass.async_block_till_done()
    await rt.module("situations").process()
    [s] = rt.module("situations").open()
    assert s.title("en") == "Clean the washer filter" and s.severity == 2

    assert hass.states.get("sensor.homeai_situations").state == "1"
    assert hass.states.get("binary_sensor.homeai_attention_needed").state == "on"
    attrs = hass.states.get("sensor.homeai_situations").attributes
    assert attrs["situations"][0]["title"] == "Clean the washer filter"

    cleared = await hass.services.async_call(
        DOMAIN, "clear_signal", {"id": "filter"}, blocking=True, return_response=True
    )
    assert cleared == {"cleared": True}


async def test_report_signal_validation(hass: HomeAssistant) -> None:
    standard_home(hass)
    await setup_homeai(hass)
    with pytest.raises(Exception):  # noqa: B017 - voluptuous rejects it before the handler
        await report(hass, id="x", title="T", severity=9)
    with pytest.raises(ServiceValidationError):
        await report(hass, id="  ", title="T")


async def test_acknowledge_all_and_entities(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    await report(hass, id="a", title="A", severity=3)
    await report(hass, id="b", title="B", severity=2)
    await hass.async_block_till_done()
    await rt.module("situations").process()
    await hass.async_block_till_done()
    result = await hass.services.async_call(DOMAIN, "acknowledge", {}, blocking=True, return_response=True)
    assert len(result["acknowledged"]) == 2
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.homeai_attention_needed").state == "off"
    assert hass.states.get("sensor.homeai_situations").state == "0"
    event = hass.states.get("event.homeai_situation")
    assert event.attributes["event_type"] == "acknowledged"


async def test_snooze_handle_dismiss_services(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    await report(hass, id="a", title="A", severity=2)
    await hass.async_block_till_done()
    engine = rt.module("situations")
    await engine.process()
    [s] = engine.open()
    r = await hass.services.async_call(
        DOMAIN, "snooze", {"situation_id": s.id, "minutes": 5}, blocking=True, return_response=True
    )
    assert r == {"snoozed": [s.id]}
    r = await hass.services.async_call(DOMAIN, "handle", {"situation_id": s.id}, blocking=True, return_response=True)
    assert r == {"handled": [s.id]} and s.handled_by == "automation"
    r = await hass.services.async_call(DOMAIN, "dismiss", {"situation_id": s.id}, blocking=True, return_response=True)
    assert r == {"dismissed": [s.id]} and not engine.open()


async def test_pause_switch_requires_admin(hass: HomeAssistant, hass_read_only_user) -> None:
    from homeassistant.core import Context
    from homeassistant.exceptions import Unauthorized

    standard_home(hass)
    rt = await setup_homeai(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.homeai_notifications_paused"}, blocking=True
    )
    assert rt.settings.get("notify.paused") is True
    assert hass.states.get("switch.homeai_notifications_paused").state == "on"
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.homeai_notifications_paused"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert rt.settings.get("notify.paused") is True


async def test_situation_websocket(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/situations/subscribe", "language": "pl"})
    msg = await client.receive_json()
    assert msg["success"]
    sub_id = msg["id"]
    msg = await client.receive_json()
    assert msg["id"] == sub_id and msg["event"] == {"type": "situations", "situations": []}

    await report(hass, id="a", title="A", severity=2)
    await hass.async_block_till_done()
    await rt.module("situations").process()
    await hass.async_block_till_done()
    msg = await client.receive_json()
    while msg["event"]["type"] != "situations" or not msg["event"]["situations"]:
        msg = await client.receive_json()
    situation = msg["event"]["situations"][0]
    assert situation["title"] == "A" and situation["phase"] == "open"

    await client.send_json_auto_id({"type": "homeai/situations/ack", "situation_id": situation["id"]})
    msg = await client.receive_json()
    while msg.get("type") != "result":
        msg = await client.receive_json()
    assert msg["success"]
    assert rt.module("situations").get(situation["id"]).acked_by

    await client.send_json_auto_id({"type": "homeai/situations/list"})
    msg = await client.receive_json()
    while msg.get("type") != "result":
        msg = await client.receive_json()
    assert [s["id"] for s in msg["result"]["open"]] == [situation["id"]]

    await client.send_json_auto_id({"type": "homeai/journal/recent"})
    msg = await client.receive_json()
    while msg.get("type") != "result":
        msg = await client.receive_json()
    assert msg["success"]


async def test_diagnostics_include_modules(hass: HomeAssistant) -> None:
    from custom_components.homeai.diagnostics import async_get_config_entry_diagnostics

    standard_home(hass)
    await setup_homeai(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert {"signals", "situations"} <= set(diag["modules"])
