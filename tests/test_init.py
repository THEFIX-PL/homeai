"""Setup, unload, WebSocket settings API and diagnostics."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.homeai.const import DOMAIN
from custom_components.homeai.diagnostics import async_get_config_entry_diagnostics

from .home import standard_home


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_websocket_settings(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    standard_home(hass)
    await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "homeai/settings/schema", "language": "pl"})
    msg = await client.receive_json()
    assert msg["success"]
    schema = msg["result"]
    assert schema["language"] == "pl"
    item = next(s for s in schema["settings"] if s["key"] == "general.language")
    assert item["label"] == "Język" and item["option_labels"]["pl"] == "Polski"
    assert {s["id"] for s in schema["sections"]} >= {"general", "world", "presence", "privacy"}

    await client.send_json_auto_id(
        {"type": "homeai/settings/set", "key": "general.journal_retention_days", "value": 10}
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["value"] == 10

    await client.send_json_auto_id(
        {"type": "homeai/settings/set", "key": "general.journal_retention_days", "value": 999}
    )
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "invalid_format"

    await client.send_json_auto_id({"type": "homeai/settings/set", "key": "privacy.level", "value": "full"})
    msg = await client.receive_json()
    assert msg["result"] == {"needs_confirmation": True}
    await client.send_json_auto_id(
        {"type": "homeai/settings/set", "key": "privacy.level", "value": "full", "confirmed": True}
    )
    assert (await client.receive_json())["success"]

    await client.send_json_auto_id(
        {"type": "homeai/settings/set", "key": "presence.role", "value": "guest", "scope": "person:person.ben"}
    )
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "homeai/settings/scope", "scope": "person:person.ben"})
    assert (await client.receive_json())["result"]["values"] == {"presence.role": "guest"}

    await client.send_json_auto_id({"type": "homeai/settings/export"})
    exported = (await client.receive_json())["result"]
    assert exported["global"]["privacy.level"] == "full"

    await client.send_json_auto_id({"type": "homeai/settings/undo"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "homeai/settings/history"})
    history = (await client.receive_json())["result"]["history"]
    assert history and history[0]["key"] == "presence.role"

    await client.send_json_auto_id({"type": "homeai/world/summary"})
    world = (await client.receive_json())["result"]
    assert {p["name"] for p in world["persons"]} == {"Anna", "Ben"}
    assert world["summary"]["areas"] == 3


async def test_settings_api_requires_admin(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, hass_read_only_access_token: str
) -> None:
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "homeai/settings/schema"})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"


async def test_diagnostics(hass: HomeAssistant) -> None:
    standard_home(hass)
    entry = await _setup(hass)
    entry.runtime_data.settings.set("general.language", "pl")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["settings"]["global"] == {"general.language": "pl"}
    assert diag["world"]["entities"] > 0
