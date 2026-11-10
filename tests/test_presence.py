"""Presence: roles, residents, sleep sources and parts of the day."""

from __future__ import annotations

from datetime import datetime, time

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.homeai.settings import SettingsManager, build_registry
from custom_components.homeai.world import Presence, WorldModel
from custom_components.homeai.world.presence import in_window

from .home import standard_home


def test_window_crossing_midnight() -> None:
    assert in_window(time(23, 30), time(23), time(7))
    assert in_window(time(3), time(23), time(7))
    assert not in_window(time(12), time(23), time(7))
    assert in_window(time(10), time(9), time(17))
    assert not in_window(time(10), time(9), time(9))


async def _presence(hass: HomeAssistant) -> Presence:
    settings = SettingsManager(hass, build_registry())
    await settings.async_load()
    world = WorldModel(hass, settings)
    await world.async_start()
    return Presence(hass, world, settings)


def _local(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return dt_util.as_utc(datetime(y, mo, d, h, mi, tzinfo=dt_util.get_default_time_zone()))


async def test_roles_and_residents(hass: HomeAssistant) -> None:
    standard_home(hass)
    p = await _presence(hass)
    p.settings.set("presence.role", "guest", skey="person:person.ben")
    names = {x.name: x for x in p.people()}
    assert names["Ben"].role == "guest"
    assert [x.name for x in p.residents()] == ["Anna"]
    assert p.someone_home()
    assert not p.everyone_away()


async def test_sleep_sources_in_order(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    p = await _presence(hass)
    anna = p.world.persons["person.anna"]
    # Tuesday 2:00 local → night hours say asleep
    freezer.move_to(_local(2026, 11, 10, 2))
    s = p.sleep(anna)
    assert (s.asleep, s.source) == (True, "hours")
    # a helper wins over hours
    home.entity("input_boolean.anna_sleeps", "off")
    p.settings.set("presence.sleep_helper", "input_boolean.anna_sleeps", skey="person:person.anna")
    s = p.sleep(anna)
    assert (s.asleep, s.source) == (False, "helper")
    # AI inference is used when helper/sensors know nothing and is before hours
    p.settings.set("presence.sleep_helper", "", skey="person:person.anna")
    p.set_ai_sleep("person.anna", False, 0.8)
    s = p.sleep(anna)
    assert (s.asleep, s.source) == (False, "ai")
    # bed sensor beats AI
    home.entity("binary_sensor.anna_bed", "on", device_class="occupancy")
    p.settings.set("presence.bed_entities", ["binary_sensor.anna_bed"], skey="person:person.anna")
    assert p.sleep(anna).source == "sensors"
    # noon: hours say awake
    p.settings.set("presence.sleep_sources", ["hours"])
    freezer.move_to(_local(2026, 11, 10, 12))
    assert not p.sleep(anna).asleep


async def test_weekend_nights(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    standard_home(hass)
    p = await _presence(hass)
    p.settings.set("presence.sleep_sources", ["hours"])
    anna = p.world.persons["person.anna"]
    # Saturday 8:00 is still the weekend night (ends 9:00); Monday 8:00 is not (ends 7:00)
    freezer.move_to(_local(2026, 11, 14, 8))
    assert p.sleep(anna).asleep
    freezer.move_to(_local(2026, 11, 16, 8))
    assert not p.sleep(anna).asleep
    # Friday 23:30 is before the weekend bedtime (00:00)
    freezer.move_to(_local(2026, 11, 13, 23, 30))
    assert not p.sleep(anna).asleep


async def test_day_parts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    standard_home(hass)
    p = await _presence(hass)
    freezer.move_to(_local(2026, 11, 10, 3))
    assert p.day_part() == "night"
    freezer.move_to(_local(2026, 11, 10, 7))
    assert p.day_part() == "morning"
    freezer.move_to(_local(2026, 11, 10, 12))
    assert p.day_part() == "day"
    freezer.move_to(_local(2026, 11, 10, 19))
    assert p.day_part() == "evening"
    freezer.move_to(_local(2026, 11, 10, 23, 30))
    assert p.day_part() == "night"
