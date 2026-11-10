"""Self-repair: playbooks run before people are told; failures escalate; protective actions on alarms."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.util import dt as dt_util

from custom_components.homeai.signals.base import Category, Need, Signal

from .common import phone_targets, phones, setup_homeai
from .home import standard_home


def failing_integration(entry_id: str) -> Signal:
    return Signal(
        id=f"integration:{entry_id}",
        detector="integrations",
        kind="integration_failed",
        category=Category.SYSTEM,
        severity=3,
        need=Need.ADMIN,
        data={"name": "Weather"},
        repair={"playbook": "reload_entry", "entry_id": entry_id},
    )


def reload_service(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    @callback
    def handle(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("homeassistant", "reload_config_entry", handle)
    return calls


async def open_with(hass: HomeAssistant, rt, signal: Signal):
    engine = rt.module("situations")
    engine.on_signals({signal.id: signal})
    await hass.async_block_till_done()
    await engine.process()
    await hass.async_block_till_done()
    return engine.open()


async def test_repair_first_then_people(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    calls = phones(hass, "anna")
    reloads = reload_service(hass)
    rt = await setup_homeai(
        hass,
        {"repair.reload_wait": 1, "repair.verify_minutes": 5, "repair.max_attempts": 1},
        overrides={
            **phone_targets("anna"),
            "person:person.anna": {**phone_targets("anna")["person:person.anna"], "presence.role": "admin"},
        },
    )
    [s] = await open_with(hass, rt, failing_integration(home.entry.entry_id))
    assert s.repair["status"] == "waiting" and s.assessment["who"] == "nobody"
    assert not calls  # nobody bothered while the home tries

    runner = rt.module("repair")
    now = dt_util.utcnow()
    await runner.tick(now + timedelta(minutes=2))
    assert reloads and reloads[0].data == {"entry_id": home.entry.entry_id}
    assert reloads[0].context.user_id == rt.system_user_id
    assert s.repair["status"] == "verifying" and s.repair["attempts"] == 1
    assert not calls

    await runner.tick(now + timedelta(minutes=8))  # still open after verification: give up, tell people
    await hass.async_block_till_done()
    assert s.repair["status"] == "failed"
    assert s.assessment["who"] == "admin"
    sent = [c for c in calls if c.data.get("message") != "clear_notification"]
    assert sent and "tried" in sent[0].data["message"]


async def test_repair_success_is_recorded(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    reload_service(hass)
    rt = await setup_homeai(hass, {"repair.reload_wait": 0, "situations.close_after": 0})
    signal = failing_integration(home.entry.entry_id)
    [s] = await open_with(hass, rt, signal)
    await rt.module("repair").tick(dt_util.utcnow() + timedelta(seconds=1))
    engine = rt.module("situations")
    engine.on_signals({signal.id: None})
    await hass.async_block_till_done()
    await engine.process()
    await engine.process()
    await hass.async_block_till_done()
    assert s.repair["status"] == "succeeded"
    assert rt.module("repair").stats["reload_entry"]["succeeded"] == 1
    assert any(e["kind"] == "repair" and e.get("result") == "succeeded" for e in rt.journal.recent(10))


async def test_retry_with_backoff_then_fail(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    reloads = reload_service(hass)
    rt = await setup_homeai(
        hass,
        {"repair.reload_wait": 0, "repair.max_attempts": 2, "repair.verify_minutes": 1, "repair.backoff_minutes": 3},
    )
    [s] = await open_with(hass, rt, failing_integration(home.entry.entry_id))
    runner = rt.module("repair")
    t = dt_util.utcnow()
    await runner.tick(t + timedelta(seconds=1))
    await runner.tick(t + timedelta(minutes=2))
    assert s.repair["status"] == "waiting"
    await runner.tick(t + timedelta(minutes=6))
    assert len(reloads) == 2 and s.repair["status"] == "verifying"
    await runner.tick(t + timedelta(minutes=8))
    assert s.repair["status"] == "failed"


async def test_person_taking_it_cancels_repair(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    reload_service(hass)
    rt = await setup_homeai(hass, {"repair.reload_wait": 5})
    [s] = await open_with(hass, rt, failing_integration(home.entry.entry_id))
    await rt.module("situations").handle(s.id, "Anna")
    assert s.repair["status"] == "cancelled"


async def test_repair_disabled(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"repair.enabled": False})
    [s] = await open_with(hass, rt, failing_integration(home.entry.entry_id))
    assert not s.repair and s.assessment["who"] == "admin"


async def test_suggested_action_needs_approval_when_proposing(hass: HomeAssistant) -> None:
    standard_home(hass)
    hass.services.async_register("light", "turn_off", lambda call: None)
    rt = await setup_homeai(
        hass, {"policy.observation_days": 0, "policy.autonomy_r1": "propose", "repair.action_wait": 0}
    )
    signal = Signal(
        id="lights_away",
        detector="lights_away",
        kind="lights_away",
        category=Category.ENERGY,
        severity=1,
        entities=("light.ceiling",),
        action={"service": "light.turn_off", "data": {"entity_id": ["light.ceiling"]}},
    )
    [s] = await open_with(hass, rt, signal)
    await rt.module("repair").tick(dt_util.utcnow() + timedelta(seconds=1))
    assert s.repair["status"] == "awaiting_approval"
    [item] = rt.module("approvals").pending()
    assert item["request"]["situation_id"] == s.id


async def test_protective_action_on_leak(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    label = home.label("Protective")
    home.entity("valve.kitchen_water", "open", area="Kitchen", labels=("Protective",))
    closed: list[ServiceCall] = []

    @callback
    def close(call: ServiceCall) -> None:
        closed.append(call)
        hass.states.async_set("valve.kitchen_water", "closed")

    hass.services.async_register("valve", "close_valve", close)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, {"world.label_protective": label}, overrides=phone_targets("anna"))
    home.set("binary_sensor.sink_leak", "on")
    rt.module("signals").evaluate()
    await hass.async_block_till_done()
    await rt.module("situations").process()
    await hass.async_block_till_done()
    assert closed and closed[0].context.user_id == rt.system_user_id
    assert hass.states.get("valve.kitchen_water").state == "closed"
    assert [c for c in calls if c.data.get("message") != "clear_notification"]  # people told at the same time
