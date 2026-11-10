"""Configuration editing through Home Assistant's own editors, as the HomeAI user, under the policy."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import label_registry as lr
from homeassistant.setup import async_setup_component
import pytest

from custom_components.homeai.actions.local_api import LocalApi
from custom_components.homeai.policy import ActionRequest

from .common import setup_homeai
from .home import standard_home

AUTOMATION = {
    "alias": "Hall light at sunset",
    "triggers": [{"trigger": "sun", "event": "sunset"}],
    "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.ceiling"}}],
}


@pytest.fixture
async def editor_home(hass: HomeAssistant, hass_client) -> Any:
    store: dict[str, Any] = {"automations.yaml": []}

    def read(path: str) -> Any:
        return store.get(path.rsplit("/", 1)[-1])

    def write(path: str, data: Any) -> None:
        store[path.rsplit("/", 1)[-1]] = data

    with (
        patch("homeassistant.components.config.view._read", side_effect=read),
        patch("homeassistant.components.config.view._write", side_effect=write),
        patch("homeassistant.components.automation.async_get_blueprints"),
    ):
        assert await async_setup_component(hass, "homeassistant", {})
        assert await async_setup_component(hass, "automation", {"automation": []})
        assert await async_setup_component(hass, "config", {})
        assert await async_setup_component(hass, "input_boolean", {})
        standard_home(hass)
        rt = await setup_homeai(hass)
        client = await hass_client()
        rt.module("executor").config.api = LocalApi(rt, base_url=str(client.make_url("")), session=client.session)
        yield rt, store


async def test_autonomous_config_change_needs_admin_approval(hass: HomeAssistant, editor_home) -> None:
    rt, store = editor_home
    result = await rt.module("executor").execute(
        ActionRequest("config", "automation_save", {"id": "homeai_sunset", "config": AUTOMATION}, reason="Hall is dark")
    )
    assert result.status == "pending_approval" and result.risk == 4
    [item] = rt.module("approvals").pending()
    assert item["approver"] == "admins"
    assert store["automations.yaml"] == []


async def test_admin_saves_reads_and_undoes_automation(hass: HomeAssistant, editor_home, hass_admin_user) -> None:
    rt, store = editor_home
    executor = rt.module("executor")

    def person(service: str, data: dict, **kw: Any) -> ActionRequest:
        return ActionRequest("config", service, data, actor="person", user_id=hass_admin_user.id, **kw)

    unconfirmed = await executor.execute(person("automation_save", {"id": "homeai_sunset", "config": AUTOMATION}))
    assert unconfirmed.status == "needs_confirmation"
    saved = await executor.execute(
        person("automation_save", {"id": "homeai_sunset", "config": AUTOMATION}, confirmed=True)
    )
    assert saved.status == "done", saved
    await hass.async_block_till_done()
    assert store["automations.yaml"][0]["id"] == "homeai_sunset"
    assert store["automations.yaml"][0]["alias"] == "Hall light at sunset"

    read = await executor.execute(person("automation_get", {"id": "homeai_sunset"}))
    assert read.status == "done" and read.data["alias"] == "Hall light at sunset"

    undone = await executor.undo(saved.action_id, hass_admin_user.id)
    assert undone.status == "done"
    await hass.async_block_till_done()
    assert store["automations.yaml"] == []


async def test_deleting_is_destructive(hass: HomeAssistant, editor_home, hass_read_only_user) -> None:
    rt, _store = editor_home
    executor = rt.module("executor")
    autonomous = await executor.execute(ActionRequest("config", "automation_delete", {"id": "x"}))
    assert autonomous.status == "denied" and autonomous.risk == 6
    member = await executor.execute(
        ActionRequest("config", "automation_delete", {"id": "x"}, actor="person", user_id=hass_read_only_user.id)
    )
    assert member.status == "denied"


async def test_helpers_and_labels(hass: HomeAssistant, editor_home, hass_admin_user) -> None:
    rt, _store = editor_home
    executor = rt.module("executor")
    created = await executor.execute(
        ActionRequest(
            "config",
            "helper_save",
            {"domain": "input_boolean", "fields": {"name": "Guests mode"}},
            actor="person",
            user_id=hass_admin_user.id,
            confirmed=True,
        )
    )
    assert created.status == "done", created
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.guests_mode") is not None
    label = await executor.execute(
        ActionRequest(
            "config", "label_save", {"name": "Garden"}, actor="person", user_id=hass_admin_user.id, confirmed=True
        )
    )
    assert label.status == "done" and lr.async_get(hass).async_get_label(label.data["label_id"]).name == "Garden"
    listed = await executor.execute(
        ActionRequest("config", "helper_list", {"domain": "input_boolean"}, actor="person", user_id=hass_admin_user.id)
    )
    assert any(item["name"] == "Guests mode" for item in listed.data)
