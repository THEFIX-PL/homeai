"""The home's plan, reminders, presence exceptions and both calendars."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest

from custom_components.homeai.const import DOMAIN
from custom_components.homeai.schedule.occurrences import between, validate_when
from custom_components.homeai.schedule.scheduler import PlanError

from .common import advance, phone_targets, phones, setup_homeai
from .home import standard_home


def switches(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    @callback
    def handle(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("switch", "turn_on", handle)
    hass.services.async_register("switch", "turn_off", handle)
    return calls


def test_when_validation(hass: HomeAssistant) -> None:
    assert validate_when({"kind": "daily", "time": "7:05"}) == {"kind": "daily", "time": "07:05"}
    with pytest.raises(ValueError):
        validate_when({"kind": "weekly", "time": "07:00", "days": [7]})
    with pytest.raises(ValueError):
        validate_when({"kind": "once", "time": "07:00", "date": "tomorrow"})
    weekly = validate_when({"kind": "weekly", "time": "08:00", "days": [0, 2]})
    start = dt_util.as_utc(datetime(2026, 11, 9, 0, 0, tzinfo=dt_util.get_default_time_zone()))  # a Monday
    found = between(hass, weekly, start, start + timedelta(days=7))
    assert [dt_util.as_local(t).weekday() for t in found] == [0, 2]
    sun = validate_when({"kind": "sun", "event": "sunset", "offset": -30})
    assert len(between(hass, sun, start, start + timedelta(days=3))) == 3


async def test_plan_runs_through_executor(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-10 06:00:00+00:00")
    standard_home(hass)
    rt = await setup_homeai(hass, {"executor.verify_seconds": 0})  # the loop clock is frozen too
    calls = switches(hass)  # after setup: HomeAI's own switch platform registers the real switch services
    scheduler = rt.module("scheduler")
    at = dt_util.as_local(dt_util.utcnow() + timedelta(minutes=10))
    entry = await scheduler.save(
        {
            "action": {"service": "switch.turn_on", "entity_ids": ["switch.coffee"]},
            "when": {"kind": "daily", "time": at.strftime("%H:%M")},
        },
        None,
    )
    assert entry["approved_risk"] == 2 and entry["title"] == "Turn on: Coffee plug"
    freezer.tick(timedelta(minutes=11))
    await advance(hass, seconds=0)
    assert calls and calls[0].context.user_id == rt.system_user_id
    assert entry["last_result"] in ("done", "unverified")
    # calendar shows the next occurrence tomorrow
    state = hass.states.get("calendar.homeai_plan")
    assert state.attributes["message"] == entry["title"]


async def test_non_admin_limits(hass: HomeAssistant, hass_read_only_user) -> None:
    standard_home(hass)
    switches(hass)
    hass.services.async_register("homeassistant", "restart", lambda call: None)
    hass.services.async_register("lock", "unlock", lambda call: None)
    rt = await setup_homeai(hass)
    scheduler = rt.module("scheduler")
    simple = await scheduler.save(
        {
            "action": {"service": "switch.turn_off", "entity_ids": ["switch.coffee"]},
            "when": {"kind": "daily", "time": "22:00"},
        },
        hass_read_only_user.id,
    )
    assert simple["author"] == hass_read_only_user.id
    with pytest.raises(PlanError, match="admin_required"):
        await scheduler.save(
            {"action": {"service": "lock.unlock"}, "when": {"kind": "daily", "time": "07:00"}}, hass_read_only_user.id
        )
    with pytest.raises(PlanError, match="never_scheduled"):
        await scheduler.save(
            {"action": {"service": "homeassistant.restart"}, "when": {"kind": "daily", "time": "03:00"}}, None
        )
    with pytest.raises(PlanError, match="unknown_service"):
        await scheduler.save({"action": {"service": "nope.nothing"}, "when": {"kind": "daily", "time": "03:00"}}, None)


async def test_skip_when_away_and_skip_dates(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass)
    calls = switches(hass)
    scheduler = rt.module("scheduler")
    entry = await scheduler.save(
        {
            "action": {"service": "switch.turn_on", "entity_ids": ["switch.coffee"]},
            "when": {"kind": "daily", "time": "07:00"},
            "skip_when_away": True,
        },
        None,
    )
    home.set("person.anna", "not_home")
    assert await scheduler.run(entry) == "skipped_away" and not calls
    tomorrow = dt_util.now().date() + timedelta(days=1)
    scheduler.skip(entry["id"], tomorrow)
    days = [
        dt_util.as_local(t).date()
        for t, _ in scheduler.occurrences(dt_util.utcnow(), dt_util.utcnow() + timedelta(days=3))
    ]
    assert tomorrow not in days


async def test_reminders_and_plan_services(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, overrides=phone_targets("anna"))
    result = await hass.services.async_call(
        DOMAIN,
        "plan_add",
        {"reminder": "Take the bins out", "kind": "weekly", "time": "19:00", "days": [1]},
        blocking=True,
        return_response=True,
    )
    scheduler = rt.module("scheduler")
    entry = scheduler.entries[result["entry_id"]]
    assert entry["title"] == "Take the bins out"
    assert await scheduler.run(entry) == "reminded"
    assert calls[-1].data["message"] == "Take the bins out"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "plan_add", {"kind": "daily", "time": "07:00"}, blocking=True, return_response=True
        )
    removed = await hass.services.async_call(
        DOMAIN, "plan_remove", {"entry_id": entry["id"]}, blocking=True, return_response=True
    )
    assert removed == {"removed": True}


async def test_missed_entries_catch_up_after_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-10 06:00:00+00:00")
    standard_home(hass)
    rt = await setup_homeai(hass, {"schedule.catch_up_minutes": 30, "executor.verify_seconds": 0})
    calls = switches(hass)
    at = dt_util.as_local(dt_util.utcnow() + timedelta(minutes=5)).strftime("%H:%M")
    await rt.module("scheduler").save(
        {
            "action": {"service": "switch.turn_on", "entity_ids": ["switch.coffee"]},
            "when": {"kind": "daily", "time": at},
        },
        None,
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(minutes=20))  # HA was down when it was due
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_presence_exceptions_and_calendar(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    module = rt.module("presence_exceptions")
    today = dt_util.now().date()
    item = module.save({"kind": "vacation", "start": today.isoformat(), "end": (today + timedelta(days=2)).isoformat()})
    assert rt.presence.vacation()
    assert module.describe(item) == "Vacation"
    await hass.async_block_till_done()
    state = hass.states.get("calendar.homeai_presence")
    assert state.state == "on" and state.attributes["message"] == "Vacation"

    module.remove(item["id"])
    assert not rt.presence.vacation()
    person = module.save({"kind": "away", "person": "person.ben", "start": today.isoformat(), "end": today.isoformat()})
    assert rt.presence.expected_away("person.ben") and not rt.presence.expected_away("person.anna")
    assert not rt.presence.vacation()  # Anna is still expected at home
    with pytest.raises(ValueError):
        module.save({"kind": "party", "start": today.isoformat(), "end": today.isoformat()})
    with pytest.raises(ValueError):
        module.save({"kind": "away", "person": "person.nobody", "start": today.isoformat(), "end": today.isoformat()})
    assert person["person"] == "person.ben"


async def test_presence_calendar_create_from_title(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    client = await hass_ws_client(hass)
    start = date.today() + timedelta(days=3)
    await client.send_json_auto_id(
        {
            "type": "calendar/event/create",
            "entity_id": "calendar.homeai_presence",
            "event": {
                "summary": "Urlop Ben",
                "dtstart": start.isoformat(),
                "dtend": (start + timedelta(days=2)).isoformat(),
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    [item] = rt.module("presence_exceptions").items.values()
    assert item["kind"] == "vacation" and item["person"] == "person.ben"
    # whole days: dtend is exclusive, so the trip covers two days
    assert (dt_util.parse_datetime(item["end"]) - dt_util.parse_datetime(item["start"])).days == 2


async def test_plan_calendar_delete_skips_occurrence(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    switches(hass)
    rt = await setup_homeai(hass)
    scheduler = rt.module("scheduler")
    entry = await scheduler.save(
        {
            "action": {"service": "switch.turn_on", "entity_ids": ["switch.coffee"]},
            "when": {"kind": "daily", "time": "07:00"},
        },
        None,
    )
    day = (dt_util.now().date() + timedelta(days=2)).isoformat()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "calendar/event/delete", "entity_id": "calendar.homeai_plan", "uid": entry["id"], "recurrence_id": day}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert day in scheduler.entries[entry["id"]]["skip_dates"]


async def test_plan_websocket(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    switches(hass)
    await setup_homeai(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "homeai/plan/save",
            "entry": {
                "action": {"service": "switch.turn_on", "entity_ids": ["switch.coffee"]},
                "when": {"kind": "daily", "time": "06:30"},
                "title": "Coffee",
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["title"] == "Coffee"
    await client.send_json_auto_id({"type": "homeai/plan/list", "days": 3})
    msg = await client.receive_json()
    assert len(msg["result"]["entries"]) == 1 and len(msg["result"]["occurrences"]) >= 2
    await client.send_json_auto_id({"type": "homeai/plan/save", "entry": {"when": {"kind": "daily", "time": "06:30"}}})
    msg = await client.receive_json()
    assert not msg["success"] and msg["error"]["message"] == "no_action"
