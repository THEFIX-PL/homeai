"""Situation lifecycle, correlation, suppression, triage and people's reactions."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.homeai.const import EVENT_SITUATION
from custom_components.homeai.signals.base import Category, Need, Signal
from custom_components.homeai.situations.model import Phase, Situation

from .common import settle, setup_homeai
from .home import standard_home


def sig(sid: str, **kw) -> Signal:
    base = {"detector": "test", "kind": kw.pop("kind", "external"), "category": Category.SYSTEM, "severity": 2}
    base.update(kw)
    base.setdefault("data", {"title": sid})
    return Signal(id=sid, **base)


async def push(hass: HomeAssistant, rt, *signals: Signal, remove: tuple[str, ...] = ()) -> None:
    engine = rt.module("situations")
    engine.on_signals({**{s.id: s for s in signals}, **dict.fromkeys(remove)})
    await hass.async_block_till_done()


async def test_leak_lifecycle(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"situations.close_after": 60})
    events: list[tuple[str, str]] = []
    hass.bus.async_listen(EVENT_SITUATION, lambda e: events.append((e.data["event"], e.data["kind"])))
    engine = rt.module("situations")

    home.set("binary_sensor.sink_leak", "on")
    await settle(hass, rt)
    [s] = engine.open()
    assert s.phase is Phase.OPEN and s.kind == "leak" and s.severity == 4
    assert s.assessment["who"] == "member" and s.assessment["urgency_minutes"] == 0
    assert s.title("en") and s.title("pl") != s.title("en")
    assert ("opened", "leak") in events

    home.set("binary_sensor.sink_leak", "off")
    await settle(hass, rt)
    assert s.phase is Phase.CLEARING

    home.set("binary_sensor.sink_leak", "on")  # comes back: same situation, reopened
    await settle(hass, rt)
    assert s.phase is Phase.OPEN
    assert any(h["event"] == "reopened" for h in s.history)

    home.set("binary_sensor.sink_leak", "off")
    await settle(hass, rt)
    await engine.process(dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert not engine.open() and engine.resolved[-1].id == s.id
    assert ("resolved", "leak") in events


async def test_flicker_never_opens(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"situations.min_duration": 120})
    engine = rt.module("situations")
    await push(hass, rt, sig("a"))
    await engine.process()
    [pending] = engine.situations.values()
    assert pending.phase is Phase.PENDING
    await push(hass, rt, remove=("a",))
    await engine.process()
    assert not engine.situations


async def test_pending_opens_after_min_duration(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"situations.min_duration": 120})
    engine = rt.module("situations")
    await push(hass, rt, sig("a"))
    await engine.process()
    await engine.process(dt_util.utcnow() + timedelta(seconds=121))
    assert [s.phase for s in engine.situations.values()] == [Phase.OPEN]


async def test_nothing_opens_during_startup_grace(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, ready=False)
    engine = rt.module("situations")
    await push(hass, rt, sig("a"))
    await engine.process()
    assert [s.phase for s in engine.situations.values()] == [Phase.PENDING]
    rt.ready = True
    await engine.process()
    assert [s.phase for s in engine.situations.values()] == [Phase.OPEN]


async def test_same_root_is_one_situation(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    engine = rt.module("situations")
    await push(hass, rt, sig("a", root="zigbee"), sig("b", root="zigbee", severity=3), sig("c"))
    await engine.process()
    groups = sorted(len(s.signals) for s in engine.open())
    assert groups == [1, 2]
    big = next(s for s in engine.open() if len(s.signals) == 2)
    assert big.primary.id == "b" and big.severity == 3


async def test_suppression_explains_other_signals(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"situations.close_after": 60})
    engine = rt.module("situations")
    internet = sig("internet", kind="internet_down", suppresses=frozenset({"cloud"}), severity=3)
    cloud1 = sig("weather", tags=frozenset({"cloud"}))
    cloud2 = sig("vacuum", tags=frozenset({"cloud"}))
    await push(hass, rt, internet, cloud1, cloud2)
    await engine.process()
    [s] = engine.open()
    assert set(s.signals) == {"internet"} and set(s.suppressed) == {"weather", "vacuum"}
    # internet back: the cloud signals would stand on their own (here they also go away)
    await push(hass, rt, remove=("internet", "weather", "vacuum"))
    await engine.process()
    assert s.phase is Phase.CLEARING


async def test_acknowledge_snooze_handle(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    engine = rt.module("situations")
    await push(hass, rt, sig("a"))
    await engine.process()
    [s] = engine.open()
    assert not s.muted()
    await engine.snooze(s.id, 10, "Anna")
    assert s.muted() and not s.muted(dt_util.utcnow() + timedelta(minutes=11))
    await engine.handle(s.id, "Ben")
    assert s.handled_by == "Ben" and s.muted()
    assert [h["event"] for h in s.history][-2:] == ["snoozed", "handled"]
    assert await engine.acknowledge("nope", "x") is None


async def test_dismiss_mutes_and_calibrates(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(
        hass,
        {"situations.dismiss_days": 3, "triage.calibration_min_events": 2, "triage.calibration_dismiss_ratio": 0.5},
    )
    engine = rt.module("situations")
    for _ in range(2):
        await push(hass, rt, sig("noisy", kind="stale_sensor", category=Category.MAINTENANCE))
        await engine.process()
        [s] = engine.open()
        await engine.dismiss(s.id, "Anna")
        assert not engine.open()
        # still reported, but muted: no new situation
        await engine.process()
        assert not engine.open()
        engine.mutes.clear()
    assert engine.stats["stale_sensor"] == {"opened": 2, "dismissed": 2}
    await engine.process()
    [s] = engine.open()
    assert "calibrated_down" in s.assessment["reasons"] and s.severity == 1


async def test_safety_is_never_calibrated_down(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"triage.calibration_min_events": 2})
    engine = rt.module("situations")
    engine.stats["leak"] = {"opened": 10, "dismissed": 10}
    await push(hass, rt, sig("leak:x", kind="leak", category=Category.SAFETY, severity=4))
    await engine.process()
    assert engine.open()[0].severity == 4


async def test_triage_context(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    critical = home.label("Critical")
    rt = await setup_homeai(hass, {"world.label_critical": critical})
    engine = rt.module("situations")
    home.set("person.anna", "not_home")  # everyone away now
    await push(hass, rt, sig("door", kind="opening_away", category=Category.SECURITY, severity=2))
    await engine.process()
    [s] = engine.open()
    assert s.severity == 3 and "everyone_away" in s.assessment["reasons"]

    home.entity("sensor.freezer", "-18", labels=(critical,))
    await push(
        hass,
        rt,
        sig("freezer", kind="stale_sensor", category=Category.MAINTENANCE, entities=("sensor.freezer",), severity=1),
    )
    await engine.process()
    freezer = next(x for x in engine.open() if x.kind == "stale_sensor")
    assert freezer.severity == 4 and "critical_label" in freezer.assessment["reasons"]


async def test_overrides_and_repair_mean_nobody(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"triage.severity_overrides": {"update_available": 0}})
    engine = rt.module("situations")
    await push(hass, rt, sig("upd", kind="update_available", need=Need.ADMIN))
    await engine.process()
    [s] = engine.open()
    assert s.severity == 0 and s.assessment["who"] == "admin"
    s.repair = {"status": "trying"}
    s.assessment = rt.module("triage").assess(s)
    assert s.assessment["who"] == "nobody" and s.assessment["fallback_who"] == "admin"


async def test_ai_assessment_kept_until_signals_change(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    engine, triage = rt.module("situations"), rt.module("triage")
    await push(hass, rt, sig("a"))
    await engine.process()
    [s] = engine.open()
    triage.apply_ai(s, {"severity": 1, "who": "nobody", "reason": "known glitch", "ignored": 1}, "p1")
    assert s.assessment["assessed_by"] == "p1" and "ignored" not in s.assessment
    assert triage.assess(s)["assessed_by"] == "p1"
    await push(hass, rt, sig("b"), sig("a", root="x"))
    s.signals["b"] = sig("b")
    assert triage.assess(s)["assessed_by"] == "code"


async def test_state_survives_restart(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    engine = rt.module("situations")
    await push(hass, rt, sig("a"))
    await engine.process()
    [s] = engine.open()
    restored = Situation.from_dict(s.as_dict())
    assert restored.as_dict() == s.as_dict()
    entry = hass.config_entries.async_entries("homeai")[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.module("situations").get(s.id) is not None


async def test_precise_wakeup_resolves_without_tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"situations.close_after": 30})
    engine = rt.module("situations")
    await push(hass, rt, sig("a"))
    await engine.process()
    await push(hass, rt, remove=("a",))
    await engine.process()
    [s] = engine.situations.values()
    assert s.phase is Phase.CLEARING
    from .common import advance

    freezer.tick(timedelta(seconds=31))
    await advance(hass, seconds=0)
    assert not engine.situations
