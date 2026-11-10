"""Executor: context, verification, undo, audit, approvals and offline cloud devices."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.setup import async_setup_component

from custom_components.homeai.const import EVENT_ACTION
from custom_components.homeai.policy import ActionRequest

from .common import phone_targets, phones, setup_homeai
from .home import standard_home


def fake_lights(hass: HomeAssistant, *, obey: bool = True) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    @callback
    def handle(call: ServiceCall) -> None:
        calls.append(call)
        ids = call.data["entity_id"]
        if obey:
            for entity_id in [ids] if isinstance(ids, str) else ids:
                hass.states.async_set(
                    entity_id, "on" if call.service == "turn_on" else "off", hass.states.get(entity_id).attributes
                )

    hass.services.async_register("light", "turn_on", handle)
    hass.services.async_register("light", "turn_off", handle)
    return calls


async def test_autonomous_action_runs_as_homeai_user(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = fake_lights(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "executor.verify_seconds": 1})
    events = []
    hass.bus.async_listen(EVENT_ACTION, callback(lambda e: events.append(e)))  # noqa: PLW0108
    result = await rt.module("executor").execute(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"]))
    assert result.status == "done" and result.risk == 1
    assert calls[0].context.user_id == rt.system_user_id
    user = await hass.auth.async_get_user(rt.system_user_id)
    assert user.system_generated and user.is_admin and user.name == "HomeAI"
    assert events[0].data["status"] == "done" and events[0].context.user_id == rt.system_user_id
    assert rt.journal.recent(1)[0]["result"] == "done"


async def test_unverified_when_state_does_not_follow(hass: HomeAssistant) -> None:
    standard_home(hass)
    fake_lights(hass, obey=False)
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "executor.verify_seconds": 0})
    result = await rt.module("executor").execute(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"]))
    assert result.status == "unverified"


async def test_person_context_and_invalid_requests(hass: HomeAssistant, hass_read_only_user) -> None:
    standard_home(hass)
    calls = fake_lights(hass)
    rt = await setup_homeai(hass)
    executor = rt.module("executor")
    result = await executor.execute(
        ActionRequest("light", "turn_on", entity_ids=["light.ceiling"], actor="person", user_id=hass_read_only_user.id)
    )
    assert result.ok and calls[-1].context.user_id == hass_read_only_user.id
    assert (await executor.execute(ActionRequest("light", "explode"))).status == "invalid"
    assert (await executor.execute(ActionRequest("light", "turn_on", entity_ids=["light.nope"]))).status == "invalid"


async def test_area_targets_are_expanded_and_classified(hass: HomeAssistant) -> None:
    standard_home(hass)
    fake_lights(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0})
    req = ActionRequest("light", "turn_off", {"area_id": "living_room"})
    assert rt.module("executor").targets(req) == ["light.ceiling"]


async def test_observing_does_nothing(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = fake_lights(hass)
    rt = await setup_homeai(hass)  # 14 days of observation by default
    result = await rt.module("executor").execute(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"]))
    assert result.status == "observed" and not calls
    assert rt.journal.recent(1)[0]["text"] == "Would have done: Turn on the light: Ceiling lamp"


async def test_undo_restores_previous_state(hass: HomeAssistant) -> None:
    standard_home(hass)
    fake_lights(hass)
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "executor.verify_seconds": 1})
    executor = rt.module("executor")
    result = await executor.execute(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"]))
    assert result.undo and hass.states.get("light.ceiling").state == "on"
    undone = await executor.undo(result.action_id)
    assert undone.status == "done"
    await hass.async_block_till_done()
    assert hass.states.get("light.ceiling").state == "off"
    assert (await executor.undo(result.action_id)).status == "invalid"


async def test_ask_creates_approval_and_approve_runs_it(hass: HomeAssistant, hass_admin_user) -> None:
    home = standard_home(hass)
    home.person("anna", "Anna", user_id=hass_admin_user.id)
    calls_phone = phones(hass, "anna")
    rt = await setup_homeai(hass, {"policy.observation_days": 0}, overrides=phone_targets("anna"))
    switched = []
    hass.services.async_register("switch", "turn_off", callback(lambda c: switched.append(c)))  # noqa: PLW0108
    result = await rt.module("executor").execute(
        ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"], reason="Saving energy")
    )
    assert result.status == "pending_approval"
    approvals = rt.module("approvals")
    [item] = approvals.pending()
    assert item["approver"] == "residents" and item["what"] == "Turn off: Coffee plug"
    request_push = [c for c in calls_phone if c.data.get("data", {}).get("tag", "").startswith("homeai_approval_")]
    assert (
        request_push and request_push[0].data["data"]["actions"][0]["action"] == f"HOMEAI_APPROVAL_APPROVE_{item['id']}"
    )
    # asking again does not create a second request
    await rt.module("executor").execute(
        ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"], reason="Saving energy")
    )
    assert len(approvals.pending()) == 1

    from homeassistant.core import Context

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"HOMEAI_APPROVAL_APPROVE_{item['id']}"},
        context=Context(user_id=hass_admin_user.id),
    )
    await hass.async_block_till_done()
    assert item["status"] == "approved" and item["decided_by"] == "Anna"
    assert switched and switched[0].context.user_id == rt.system_user_id


async def test_non_admin_cannot_approve_admin_requests(hass: HomeAssistant, hass_read_only_user) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    home = standard_home(hass)
    home.person("ben", "Ben", user_id=hass_read_only_user.id)
    rt = await setup_homeai(hass)
    result = await rt.module("executor").execute(
        ActionRequest("homeassistant", "reload_config_entry", {"entry_id": "x"})
    )
    assert result.status == "pending_approval"
    approvals = rt.module("approvals")
    assert await approvals.approve(result.approval_id, hass_read_only_user.id) is None
    assert await approvals.approve(result.approval_id, None) is None
    assert approvals.items[result.approval_id]["status"] == "pending"


async def test_approvals_expire(hass: HomeAssistant) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    assert await async_setup_component(hass, "homeassistant", {})
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.approval_minutes": 5})
    result = await rt.module("executor").execute(
        ActionRequest("homeassistant", "reload_config_entry", {"entry_id": "x"})
    )
    approvals = rt.module("approvals")
    await approvals.tick(dt_util.utcnow() + timedelta(minutes=6))
    assert approvals.items[result.approval_id]["status"] == "expired"


async def test_cloud_devices_blocked_while_offline(hass: HomeAssistant) -> None:
    from custom_components.homeai.signals.base import Category, Signal

    standard_home(hass)
    fake_lights(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0})
    hub = rt.module("signals")
    hub.signals["internet_down"] = Signal(
        id="internet_down", detector="internet", kind="internet_down", category=Category.SYSTEM, severity=3
    )
    from custom_components.homeai.signals.detectors import system

    original = system.device_tags
    system.device_tags = lambda ctx, device_id: frozenset({"cloud"})
    try:
        result = await rt.module("executor").execute(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"]))
    finally:
        system.device_tags = original
    assert result.status == "blocked" and result.message == "internet_down"


async def test_system_user_removed_with_entry(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    user_id = rt.system_user_id
    entry = hass.config_entries.async_entries("homeai")[0]
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.auth.async_get_user(user_id) is None


async def test_system_user_reused_after_reload(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    user_id = rt.system_user_id
    entry = hass.config_entries.async_entries("homeai")[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.system_user_id == user_id
    assert entry.runtime_data.installed_at == rt.installed_at


async def test_logbook_entry_names_homeai(hass: HomeAssistant) -> None:
    standard_home(hass)
    fake_lights(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "executor.verify_seconds": 1})
    hass.config.components.add("logbook")
    entries = []
    hass.bus.async_listen("logbook_entry", callback(lambda e: entries.append(e)))  # noqa: PLW0108
    await rt.module("executor").execute(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"]))
    await hass.async_block_till_done()
    assert entries and entries[0].data["name"] == "HomeAI" and entries[0].data["entity_id"] == "light.ceiling"
    assert entries[0].context.user_id == rt.system_user_id


async def test_plain_descriptions(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.entity("climate.living", "heat", area="Living room", attrs={"friendly_name": "Thermostat"})
    rt = await setup_homeai(hass, {"general.language": "pl"})
    executor = rt.module("executor")
    request = ActionRequest("climate", "set_temperature", {"temperature": 24}, entity_ids=["climate.living"])
    assert executor.describe(request) == "Ustaw Thermostat na 24 °C"
    assert executor.describe(ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"])) == "Wyłącz: Coffee plug"
    assert executor.describe(ActionRequest("climate", "set_temperature", {}, entity_ids=["climate.living"])) == (
        "climate.set_temperature: Thermostat"  # a value is missing: the plain service name
    )
    assert executor.describe(ActionRequest("vacuum", "start", entity_ids=[])) == "vacuum.start: —"
