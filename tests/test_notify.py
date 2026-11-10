"""Notification router: ladders, recipients, sleep, limits, phone actions, clearing and digest."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.homeai.const import EVENT_NOTIFICATION
from custom_components.homeai.signals.base import Category, Signal

from .common import phone_targets, phones, setup_homeai
from .home import standard_home


def leak() -> Signal:
    return Signal(
        id="leak:x",
        detector="safety",
        kind="leak",
        category=Category.SAFETY,
        severity=4,
        data={"name": "Sink leak", "where": "Kitchen"},
    )


def minor(severity: int = 2, sid: str = "minor") -> Signal:
    return Signal(
        id=sid,
        detector="test",
        kind="external",
        category=Category.SYSTEM,
        severity=severity,
        data={"title": f"Something {sid}"},
    )


async def open_with(hass: HomeAssistant, rt, *signals: Signal):
    engine = rt.module("situations")
    engine.on_signals({s.id: s for s in signals})
    await hass.async_block_till_done()
    await engine.process()
    await hass.async_block_till_done()
    return engine.open()


def pushes(calls, service: str | None = None) -> list:
    return [
        c for c in calls if (service is None or c.service == service) and c.data.get("message") != "clear_notification"
    ]


async def test_critical_goes_to_everyone_with_actions(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna", "ben")
    rt = await setup_homeai(hass, overrides=phone_targets("anna", "ben"))
    events: list[dict] = []
    hass.bus.async_listen(EVENT_NOTIFICATION, lambda e: events.append(dict(e.data)))
    [s] = await open_with(hass, rt, leak())
    sent = pushes(calls)
    assert {c.service for c in sent} == {"mobile_app_anna", "mobile_app_ben"}
    data = sent[0].data["data"]
    assert data["push"]["interruption-level"] == "critical"
    assert [a["action"] for a in data["actions"]] == [f"HOMEAI_{v}_{s.id}" for v in ("ACK", "HANDLE", "SNOOZE")]
    assert events and events[0]["state"] == "active" and events[0]["critical"]
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert f"homeai_{s.id}" in notifications
    # a second pass sends nothing new (no repeat due yet)
    await rt.module("notify").deliver(s)
    assert len(pushes(calls)) == 2


async def test_medium_goes_to_people_at_home_only(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna", "ben")
    rt = await setup_homeai(hass, overrides=phone_targets("anna", "ben"))
    await open_with(hass, rt, minor(2))
    assert [c.service for c in pushes(calls)] == ["mobile_app_anna"]


async def test_home_or_all_falls_back_to_everyone(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.set("person.anna", "not_home")
    calls = phones(hass, "anna", "ben")
    rt = await setup_homeai(hass, overrides=phone_targets("anna", "ben"))
    await open_with(hass, rt, minor(2))
    assert {c.service for c in pushes(calls)} == {"mobile_app_anna", "mobile_app_ben"}


async def test_escalation_step_after_minutes(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna", "ben")
    rt = await setup_homeai(hass, overrides=phone_targets("anna", "ben"))
    [s] = await open_with(hass, rt, minor(3))
    assert [c.service for c in pushes(calls)] == ["mobile_app_anna"]
    router = rt.module("notify")
    await router.deliver(s, dt_util.utcnow() + timedelta(minutes=16))
    assert {c.service for c in pushes(calls)} == {"mobile_app_anna", "mobile_app_ben"}


async def test_low_severity_has_no_push(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, overrides=phone_targets("anna"))
    [s] = await open_with(hass, rt, minor(1))
    assert not pushes(calls)
    assert f"homeai_{s.id}" in persistent_notification._async_get_or_create_notifications(hass)


async def test_sleeping_people_only_get_critical(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.entity("input_boolean.anna_sleeps", "on")
    calls = phones(hass, "anna", "ben")
    overrides = phone_targets("anna", "ben")
    overrides["person:person.anna"]["presence.sleep_helper"] = "input_boolean.anna_sleeps"
    rt = await setup_homeai(hass, overrides=overrides)
    await open_with(hass, rt, minor(2))
    assert pushes(calls) == []  # Anna (home) sleeps; Ben is away and not a "home" recipient
    await open_with(hass, rt, leak())
    assert "mobile_app_anna" in {c.service for c in pushes(calls)}


async def test_paused_and_critical_exception(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, {"notify.paused": True}, overrides=phone_targets("anna"))
    await open_with(hass, rt, minor(3))
    assert not pushes(calls)
    await open_with(hass, rt, leak())
    assert pushes(calls)


async def test_daily_limit_counts_only_delivered(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, {"notify.max_per_day": 2}, overrides=phone_targets("anna"))
    for i in range(4):
        await open_with(hass, rt, minor(2, f"m{i}"))
    assert len(pushes(calls)) == 2


async def test_phone_action_acknowledges_and_clears(hass: HomeAssistant, hass_admin_user) -> None:
    home = standard_home(hass)
    home.person("anna", "Anna", user_id=hass_admin_user.id)
    calls = phones(hass, "anna", "ben")
    rt = await setup_homeai(hass, overrides=phone_targets("anna", "ben"))
    [s] = await open_with(hass, rt, leak())
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": f"HOMEAI_ACK_{s.id}"}, context=Context(user_id=hass_admin_user.id)
    )
    await hass.async_block_till_done()
    assert s.acked_by == "Anna" and s.muted()
    clears = [c for c in calls if c.data.get("message") == "clear_notification"]
    assert {c.service for c in clears} == {"mobile_app_anna", "mobile_app_ben"}
    # acknowledged: escalation stops
    before = len(pushes(calls))
    await rt.module("notify").deliver(s, dt_util.utcnow() + timedelta(hours=1))
    assert len(pushes(calls)) == before


async def test_resolved_clears_persistent_and_event(hass: HomeAssistant) -> None:
    standard_home(hass)
    phones(hass, "anna")
    rt = await setup_homeai(hass, overrides=phone_targets("anna"))
    events: list[dict] = []
    hass.bus.async_listen(EVENT_NOTIFICATION, lambda e: events.append(dict(e.data)))
    [s] = await open_with(hass, rt, minor(1))
    engine = rt.module("situations")
    engine.on_signals({"minor": None})
    await hass.async_block_till_done()
    await engine.process()
    await engine.process()
    await hass.async_block_till_done()
    assert f"homeai_{s.id}" not in persistent_notification._async_get_or_create_notifications(hass)
    assert events[-1]["state"] == "cleared" and events[-1]["reason"] == "resolved"


async def test_who_nobody_stays_quiet(hass: HomeAssistant) -> None:
    """While a repair playbook is trying, nobody is needed and nobody is notified."""
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, overrides=phone_targets("anna"))
    engine = rt.module("situations")

    async def repairing(event, sit):
        if event == "opened":
            sit.repair = {"status": "trying"}

    engine.processors.insert(0, ("repair", repairing))
    [s] = await open_with(hass, rt, minor(3, "m"))
    assert s.assessment["who"] == "nobody"
    assert not pushes(calls)


async def test_digest(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, overrides=phone_targets("anna"))
    router = rt.module("notify")
    assert await router.send_digest() is False  # nothing open
    await open_with(hass, rt, minor(1, "a"), minor(1, "b"))
    assert await router.send_digest()
    digest = [c for c in calls if c.data.get("data", {}).get("tag") == "homeai_digest"]
    assert digest and "Something" in digest[0].data["message"]


async def test_notify_entity_target(hass: HomeAssistant) -> None:
    standard_home(hass)
    sent = []
    hass.states.async_set("notify.kitchen_display", "unknown")
    hass.services.async_register("notify", "send_message", sent.append)
    rt = await setup_homeai(
        hass,
        overrides={"person:person.anna": {"notify.targets": ["notify.kitchen_display"], "notify.discover_apps": False}},
    )
    await open_with(hass, rt, minor(2))
    assert sent and sent[0].data["entity_id"] in ("notify.kitchen_display", ["notify.kitchen_display"])
