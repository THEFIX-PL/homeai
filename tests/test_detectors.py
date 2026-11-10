"""Detectors on a synthetic home: what each one notices and what it ignores."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.homeai.signals.detectors.external import parse_external

from .common import settle, setup_homeai
from .home import standard_home


async def test_leak_is_a_critical_safety_signal(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass)
    hub = rt.module("signals")
    assert not [s for s in hub.signals.values() if s.kind == "leak"]

    home.set("binary_sensor.sink_leak", "on")
    changes = hub.evaluate()
    leak = changes["leak:binary_sensor.sink_leak"]
    assert leak is not None
    assert leak.severity == 4 and leak.category == "safety" and leak.data["name"] == "Sink leak"
    assert leak.area_id == "kitchen"

    home.set("binary_sensor.sink_leak", "off")
    assert hub.evaluate()["leak:binary_sensor.sink_leak"] is None


async def test_safety_severity_is_a_setting(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"detectors.safety.severity_leak": 3})
    home.set("binary_sensor.sink_leak", "on")
    assert rt.module("signals").evaluate()["leak:binary_sensor.sink_leak"].severity == 3


async def test_disabled_detector_reports_nothing(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"detectors.safety.enabled": False})
    home.set("binary_sensor.sink_leak", "on")
    rt.module("signals").evaluate()
    assert "leak:binary_sensor.sink_leak" not in rt.module("signals").signals


async def test_low_battery_of_a_protective_device_is_raised(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass)
    hub = rt.module("signals")
    home.set("sensor.sink_leak_battery", "9")
    signal = next(s for s in hub.evaluate().values() if s and s.kind == "battery_low")
    assert signal.data["level"] == "9%"
    assert signal.data["name"] == "Sink leak sensor"
    # a leak sensor protects the home: its battery matters more than an ordinary one
    assert signal.severity >= int(rt.settings.get("detectors.battery.safety_severity"))


async def test_battery_threshold_per_entity(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, overrides={"entity:sensor.sink_leak_battery": {"detectors.battery.threshold": 90}})
    home.set("sensor.sink_leak_battery", "85")
    assert any(s and s.kind == "battery_low" for s in rt.module("signals").evaluate().values())


async def test_open_window_while_everyone_is_away(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"detectors.security.away_minutes": 5})
    hub = rt.module("signals")
    home.set("binary_sensor.bedroom_window", "on")
    home.set("person.anna", "not_home")
    assert not [s for s in hub.evaluate().values() if s and s.detector == "security"]
    freezer.tick(timedelta(minutes=6))
    found = [s for s in hub.evaluate().values() if s and s.detector == "security"]
    assert found and found[0].entities == ("binary_sensor.bedroom_window",)
    home.set("person.anna", "home")
    assert any(v is None for k, v in hub.evaluate().items() if k.startswith(found[0].id))


async def test_lights_on_while_away_suggests_turning_off(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"detectors.lights_away.minutes": 1})
    hub = rt.module("signals")
    home.set("person.anna", "not_home")
    home.set("light.ceiling", "on")
    freezer.tick(timedelta(minutes=2))
    signal = next(s for s in hub.evaluate().values() if s and s.kind == "lights_away")
    assert signal.action and signal.action["service"] == "light.turn_off"
    assert "light.ceiling" in signal.entities


async def test_environment_needs_sustained_condition(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"detectors.environment.minutes": 10})
    hub = rt.module("signals")
    home.set("sensor.bedroom_temperature", "35")
    assert not [s for s in hub.evaluate().values() if s and s.detector == "environment"]
    freezer.tick(timedelta(minutes=11))
    found = [s for s in hub.evaluate().values() if s and s.detector == "environment"]
    assert found and found[0].kind == "temperature_high"


async def test_unavailable_devices(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"detectors.availability.minutes": 5})
    hub = rt.module("signals")
    home.set("light.ceiling", "unavailable")
    freezer.tick(timedelta(minutes=6))
    found = [s for s in hub.evaluate().values() if s and s.detector == "availability"]
    assert found and found[0].data["name"] == "Ceiling lamp"


async def test_external_attribute_contract(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass)
    home.entity(
        "sensor.washer",
        "idle",
        area="Kitchen",
        attrs={
            "homeai_signals": [
                {"id": "filter", "title": "Clean the filter", "severity": 2, "category": "maintenance"},
                {"id": "bad", "severity": 9},
            ]
        },
    )
    found = [s for s in rt.module("signals").evaluate().values() if s and s.kind == "external"]
    assert len(found) == 1
    assert found[0].id == "external:sensor.washer:filter" and found[0].area_id == "kitchen"


def test_parse_external_validation() -> None:
    assert parse_external({"id": "x", "title": "T"}, source="s").severity == 1
    assert parse_external({"id": "x", "title": "T", "severity": True}, source="s") is None
    assert parse_external({"id": "", "title": "T"}, source="s") is None
    assert parse_external({"id": "x", "title": "T", "category": "nope"}, source="s") is None
    assert parse_external("x", source="s") is None


async def test_appliance_sensors_are_not_the_room(hass: HomeAssistant) -> None:
    """A freezer's thermometer in the kitchen is not a cold kitchen; a custom rule watches it instead."""
    home = standard_home(hass)
    freezer = home.device("Zamrażarka", area="Kitchen")
    home.entity(
        "sensor.freezer_temperature",
        "-18",
        device=freezer,
        device_class="temperature",
        attrs={"unit_of_measurement": "°C", "friendly_name": "Zamrażarka Temperatura"},
    )
    home.entity(
        "sensor.kitchen_temperature",
        "8",
        area="Kitchen",
        device_class="temperature",
        attrs={"unit_of_measurement": "°C", "friendly_name": "Kitchen temperature"},
    )
    rt = await setup_homeai(hass, {"detectors.environment.minutes": 0})
    await settle(hass, rt)
    cold = {s.id for s in rt.module("signals").signals.values() if s.kind == "temperature_low"}
    assert cold == {"temperature_low:sensor.kitchen_temperature"}
    rt.settings.set("detectors.environment.appliance_words", [])
    await settle(hass, rt)
    cold = {s.id for s in rt.module("signals").signals.values() if s.kind == "temperature_low"}
    assert "temperature_low:sensor.freezer_temperature" in cold


async def test_backup_never_succeeded_says_so(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.entity(
        "sensor.backup_last_successful",
        "unknown",
        platform="backup",
        translation_key="last_successful_automatic_backup",
        category="diagnostic",
    )
    rt = await setup_homeai(hass)
    await settle(hass, rt)
    [s] = [s for s in rt.module("situations").open() if s.kind == "backup_stale"]
    assert s.description("en") == "No automatic backup has succeeded yet."
    assert s.description("pl") == "Nie ma jeszcze żadnej udanej automatycznej kopii."
    hass.states.async_set("sensor.backup_last_successful", (dt_util.utcnow() - timedelta(days=3)).isoformat())
    await settle(hass, rt)
    [s] = [s for s in rt.module("situations").open() if s.kind == "backup_stale"]
    assert s.description("en").startswith("Last successful automatic backup: ")
