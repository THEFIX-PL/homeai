"""“Tell me when” commitments, plans from other integrations, plant watering and notification templates."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.calendar import DOMAIN as CALENDAR_DOMAIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest

from custom_components.homeai.const import DOMAIN
from custom_components.homeai.schedule.commitments import CommitmentError, met

from .common import phone_targets, phones, settle, setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home
from .test_notify import leak, open_with, pushes


def test_conditions() -> None:
    assert met("state", "off", "on", "off") and not met("state", "off", "on", "unavailable")
    assert met("not_state", "running", "running", "idle")
    assert met("above", 30, "20", "31.5") and not met("above", 30, "20", "abc")
    assert met("below", 5, "8", "4") and met("changes", None, "a", "b") and not met("changes", None, None, "b")


async def test_tell_me_when(hass: HomeAssistant, hass_admin_user, hass_ws_client) -> None:
    home = standard_home(hass)
    home.person("owner", "Owner", user_id=hass_admin_user.id)
    home.entity("sensor.washer", "running", area="Kitchen", attrs={"friendly_name": "Washer"})
    rt = await setup_homeai(hass, overrides=phone_targets("owner"))
    calls = phones(hass, "owner")
    result = await hass.services.async_call(
        DOMAIN,
        "watch",
        {"entity_id": "sensor.washer", "condition": "state", "value": "idle", "message": "Laundry is done"},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    commitments = rt.module("commitments")
    assert result["watch_id"] in commitments.items
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/watches/list"})
    msg = await client.receive_json()
    assert msg["result"]["items"][0]["what"] == "Washer becomes idle"

    hass.states.async_set("sensor.washer", "rinsing")
    await hass.async_block_till_done()
    assert not pushes(calls)
    hass.states.async_set("sensor.washer", "idle")
    await hass.async_block_till_done()
    sent = pushes(calls)
    assert [c.data["message"] for c in sent] == ["Laundry is done"] and not commitments.items
    hass.states.async_set("sensor.washer", "running")
    hass.states.async_set("sensor.washer", "idle")
    await hass.async_block_till_done()
    assert len(pushes(calls)) == 1  # told once


async def test_commitment_limits(hass: HomeAssistant, hass_admin_user) -> None:
    home = standard_home(hass)
    home.person("owner", "Owner", user_id=hass_admin_user.id)
    rt = await setup_homeai(hass, {"schedule.watch_max": 1, "schedule.watch_hours": 2})
    commitments = rt.module("commitments")
    with pytest.raises(CommitmentError, match="person_required"):
        commitments.add(None, "light.ceiling", "changes")
    with pytest.raises(CommitmentError, match="value_number"):
        commitments.add(hass_admin_user.id, "sensor.bedroom_temperature", "above", "warm")
    item = commitments.add(hass_admin_user.id, "light.ceiling", "state", "on", hours=100)
    assert dt_util.parse_datetime(item["expires"]) <= dt_util.utcnow() + timedelta(hours=2, seconds=1)
    with pytest.raises(CommitmentError, match="too_many"):
        commitments.add(hass_admin_user.id, "light.ceiling", "changes")
    commitments.expire(dt_util.utcnow() + timedelta(hours=3))
    assert not commitments.items
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "watch", {"entity_id": "light.ceiling", "condition": "changes"}, blocking=True, return_response=True
        )


async def test_watch_from_a_conversation(hass: HomeAssistant, hass_admin_user) -> None:
    home = standard_home(hass)
    home.person("owner", "Owner", user_id=hass_admin_user.id)
    rt = await setup_homeai(hass, subentries=[tier()])
    fake = FakeProvider(
        [
            {
                "tool_calls": [
                    ("watch", {"entity_id": "binary_sensor.bedroom_window", "condition": "state", "value": "on"})
                ]
            },
            {"text": "I will tell you."},
        ]
    )
    install(rt, "p1", fake)
    reply, actions = await rt.module("ai").chat("Tell me when the window opens", "w", hass_admin_user.id)
    assert reply == "I will tell you." and actions[0]["what"] == "Bedroom window becomes on"
    assert [i["entity_id"] for i in rt.module("commitments").items.values()] == ["binary_sensor.bedroom_window"]


async def test_plans_from_other_integrations(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    start = dt_util.utcnow() + timedelta(hours=3)
    hass.states.async_set(
        "sensor.dishwasher_program",
        "eco",
        {
            "friendly_name": "Dishwasher",
            "homeai_plan": [
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=2)).isoformat(),
                    "title": "Dishwasher eco",
                },
                {"start": "not a date", "title": "Broken"},
                {"title": "No start"},
            ],
        },
    )
    rt = await setup_homeai(hass)
    scheduler = rt.module("scheduler")
    now = dt_util.utcnow()
    assert scheduler.occurrences(now, now + timedelta(days=1)) == []  # never run by HomeAI
    [(at, item)] = scheduler.external(now, now + timedelta(days=1))
    assert item["title"] == "Dishwasher eco" and item["source"] == "sensor.dishwasher_program"
    assert abs((at - start).total_seconds()) < 1
    events = await hass.services.async_call(
        CALENDAR_DOMAIN,
        "get_events",
        {"entity_id": "calendar.homeai_plan", "duration": {"hours": 24}},
        blocking=True,
        return_response=True,
    )
    [event] = events["calendar.homeai_plan"]["events"]
    assert event["summary"] == "Dishwasher eco"
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/plan/list", "days": 2})
    msg = await client.receive_json()
    assert msg["result"]["occurrences"][0]["external"] is True
    rt.settings.set("schedule.external_plans", False)
    assert scheduler.external(now, now + timedelta(days=1)) == []


async def test_watering(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    plant = home.device("Fern sensor", area="Living room")
    home.entity(
        "sensor.fern_moisture",
        "12",
        device=plant,
        device_class="moisture",
        attrs={"unit_of_measurement": "%", "friendly_name": "Fern moisture"},
    )
    home.entity(
        "sensor.cactus_moisture",
        "8",
        area="Living room",
        device_class="moisture",
        attrs={"unit_of_measurement": "%", "friendly_name": "Cactus moisture"},
    )
    rt = await setup_homeai(hass, overrides={"entity:sensor.cactus_moisture": {"detectors.watering.min": 5}})
    await settle(hass, rt)
    signals = {s.id: s for s in rt.module("signals").signals.values() if s.kind == "plant_dry"}
    assert set(signals) == {"watering:sensor.fern_moisture"}
    [s] = [s for s in rt.module("situations").open() if s.kind == "plant_dry"]
    assert s.title("en") == "Water the plant: Fern sensor"
    hass.states.async_set("sensor.fern_moisture", "45", {"unit_of_measurement": "%"})
    await settle(hass, rt)
    assert not [x for x in rt.module("signals").signals.values() if x.kind == "plant_dry"]


async def test_notification_templates(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(
        hass,
        {
            "notify.template_title": "{{ title }} [{{ severity }}]",
            "notify.template_message": "{{ description }} — {{ who_text | lower }}",
        },
    )
    [s] = await open_with(hass, rt, leak())
    router = rt.module("notify")
    title, message = router.message(s)
    assert title == f"{s.title('en')} [4]" and message.startswith(s.description("en") + " — ")
    rt.settings.set("notify.template_title", "{{ broken ")
    rt.settings.set("notify.template_message", "{{ '' }}")
    title, message = router.message(s)
    assert title == s.title("en") and s.description("en") in message  # broken or empty: the built-in text
