"""Panel commands: chat threads, overrides per place or thing, settings history and import."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .common import setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home


async def test_chat_send_and_history(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier()])
    install(rt, "p1", FakeProvider([{"text": "All quiet."}, {"text": "Still quiet."}]))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/chat/send", "text": "How is the house?"})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["reply"] == "All quiet." and msg["result"]["ai"] is True
    conversation = msg["result"]["conversation_id"]
    await client.send_json_auto_id({"type": "homeai/chat/send", "text": "And now?", "conversation_id": conversation})
    msg = await client.receive_json()
    assert msg["result"]["reply"] == "Still quiet." and msg["result"]["conversation_id"] == conversation
    await client.send_json_auto_id({"type": "homeai/chat/history", "conversation_id": conversation})
    msg = await client.receive_json()
    assert [(m["role"], m["text"]) for m in msg["result"]["messages"]] == [
        ("user", "How is the house?"),
        ("assistant", "All quiet."),
        ("user", "And now?"),
        ("assistant", "Still quiet."),
    ]
    # Another person's thread is not readable.
    rt.module("ai").threads[conversation]["user_id"] = "someone-else"
    await client.send_json_auto_id({"type": "homeai/chat/history", "conversation_id": conversation})
    msg = await client.receive_json()
    assert msg["result"]["messages"] == []


async def test_chat_without_ai(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    await setup_homeai(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/chat/send", "text": "Status?"})
    msg = await client.receive_json()
    assert msg["result"]["ai"] is False and msg["result"]["conversation_id"].startswith("panel-")


async def test_scope_overrides(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    client = await hass_ws_client(hass)
    key = "detectors.battery.threshold"
    await client.send_json_auto_id({"type": "homeai/settings/set", "key": key, "value": 35, "scope": "area:kitchen"})
    msg = await client.receive_json()
    assert msg["success"]
    await client.send_json_auto_id({"type": "homeai/settings/scope", "scope": "area:kitchen"})
    msg = await client.receive_json()
    assert msg["result"]["values"] == {key: 35}
    assert rt.settings.get(key) == 20
    # A setting that cannot be overridden for a room is refused.
    await client.send_json_auto_id(
        {"type": "homeai/settings/set", "key": "general.assistant_name", "value": "X", "scope": "area:kitchen"}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    await client.send_json_auto_id({"type": "homeai/settings/history", "limit": 5})
    msg = await client.receive_json()
    assert msg["result"]["history"][0]["scope"] == "area:kitchen" and msg["result"]["history"][0]["new"] == 35
    await client.send_json_auto_id({"type": "homeai/settings/reset", "key": key, "scope": "area:kitchen"})
    msg = await client.receive_json()
    await client.send_json_auto_id({"type": "homeai/settings/scope", "scope": "area:kitchen"})
    msg = await client.receive_json()
    assert msg["result"]["values"] == {}


async def test_import_settings(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    client = await hass_ws_client(hass)
    data = {"global": {"notify.max_per_day": 7}, "overrides": {"area:kitchen": {"detectors.battery.threshold": 30}}}
    await client.send_json_auto_id({"type": "homeai/settings/import", "data": data})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["changed"] >= 2
    assert rt.settings.get("notify.max_per_day") == 7
    assert rt.settings.overrides_for("area:kitchen") == {"detectors.battery.threshold": 30}
