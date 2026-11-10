"""World model: roles, indexes, exclusions, labels and incremental updates."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.homeai.settings import SettingsManager, build_registry
from custom_components.homeai.world import Role, WorldModel, classify

from .home import standard_home


def test_classify_by_domain_and_device_class() -> None:
    assert Role.LEAK in classify("binary_sensor", {"device_class": "moisture"})
    assert Role.WINDOW in classify("binary_sensor", {}, device_class="window")
    assert Role.OUTLET in classify("switch", {"device_class": "outlet"})
    assert Role.SWITCH in classify("switch", {})
    assert Role.GARAGE_DOOR in classify("cover", {"device_class": "garage"})
    assert Role.CONTROLLABLE in classify("light", {})
    assert Role.CONSUMABLE in classify("sensor", {"unit_of_measurement": "%"}, translation_key="filter_life")
    assert Role.CONSUMABLE not in classify("sensor", {"unit_of_measurement": "%", "device_class": "battery"})
    assert Role.LAST_SEEN in classify("sensor", {"device_class": "timestamp"}, entity_id="sensor.x_last_seen")
    assert classify("sensor", {"unit_of_measurement": "%"}, entity_id="sensor.cpu_load") == frozenset()


async def _world(hass: HomeAssistant) -> WorldModel:
    settings = SettingsManager(hass, build_registry())
    await settings.async_load()
    world = WorldModel(hass, settings)
    await world.async_start()
    return world


async def test_indexes_and_areas(hass: HomeAssistant) -> None:
    standard_home(hass)
    world = await _world(hass)
    assert world.with_role(Role.LEAK) == {"binary_sensor.sink_leak"}
    assert "sensor.sink_leak_battery" in world.with_role(Role.BATTERY)
    kitchen = next(a for a in world.areas.values() if a.name == "Kitchen")
    assert world.in_area(kitchen.area_id) >= {"switch.coffee", "binary_sensor.sink_leak"}
    info = world.entity("binary_sensor.sink_leak")
    assert info is not None and info.area_id == kitchen.area_id and info.floor_id is not None
    assert world.area_name(kitchen.area_id) == "Kitchen"
    assert set(world.persons) == {"person.anna", "person.ben"}
    assert world.summary()["entities"] >= 6
    await world.async_stop()


async def test_labels_created_and_ignore_label(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    world = await _world(hass)
    assert home.labels.async_get_label("homeai_ignore") is not None
    er.async_get(hass).async_update_entity("switch.coffee", labels={"homeai_ignore"})
    await hass.async_block_till_done()
    assert world.entity("switch.coffee") is None
    assert "switch.coffee" not in world.with_role(Role.OUTLET)
    await world.async_stop()


async def test_new_entity_and_device_class_change(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    world = await _world(hass)
    events: list[tuple[str, set[str]]] = []
    world.listen(lambda kind, ids: events.append((kind, ids)))
    home.entity("binary_sensor.door", "off", area="Kitchen", device_class="door")
    await hass.async_block_till_done()
    assert "binary_sensor.door" in world.with_role(Role.DOOR)
    hass.states.async_set("sensor.plain", "1", {})
    await hass.async_block_till_done()
    assert world.entity("sensor.plain") is not None
    hass.states.async_set("sensor.plain", "1", {"device_class": "temperature"})
    await hass.async_block_till_done()
    assert "sensor.plain" in world.with_role(Role.TEMPERATURE)
    assert any(kind == "entity" for kind, _ in events)
    await world.async_stop()


async def test_exclusion_patterns_and_scope(hass: HomeAssistant) -> None:
    standard_home(hass)
    world = await _world(hass)
    world.settings.set("world.exclude_entities", ["switch.*"])
    await world._rebuild_and_notify()
    assert world.entity("switch.coffee") is None
    bedroom = next(a.area_id for a in world.areas.values() if a.name == "Bedroom")
    world.settings.set("world.scope", "selected")
    world.settings.set("world.include_areas", [bedroom])
    await world._rebuild_and_notify()
    assert world.entity("binary_sensor.sink_leak") is None
    assert world.entity("binary_sensor.bedroom_window") is not None
    assert "person.anna" in world.persons
    await world.async_stop()
