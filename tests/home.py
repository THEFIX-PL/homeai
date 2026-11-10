"""Build synthetic homes in a test Home Assistant: floors, areas, devices, entities, states and people."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


class Home:
    """Fluent builder for a fake home."""

    def __init__(self, hass: HomeAssistant, platform: str = "fake_home") -> None:
        self.hass = hass
        self.platform = platform
        self.entry = MockConfigEntry(domain=platform, title=platform.title(), state=ConfigEntryState.LOADED)
        self.entry.add_to_hass(hass)
        self.areas = ar.async_get(hass)
        self.floors = fr.async_get(hass)
        self.devices = dr.async_get(hass)
        self.entities = er.async_get(hass)
        self.labels = lr.async_get(hass)

    def floor(self, name: str, level: int = 0) -> str:
        f = self.floors.async_get_floor_by_name(name) or self.floors.async_create(name, level=level)
        return f.floor_id

    def area(self, name: str, floor: str | None = None) -> str:
        a = self.areas.async_get_area_by_name(name) or self.areas.async_create(name)
        if floor:
            self.areas.async_update(a.id, floor_id=self.floor(floor))
        return a.id

    def label(self, name: str) -> str:
        label = self.labels.async_get_label_by_name(name) or self.labels.async_create(name)
        return label.label_id

    def device(
        self,
        name: str,
        area: str | None = None,
        labels: tuple[str, ...] = (),
        identifiers: tuple[str, str] | None = None,
        entry: MockConfigEntry | None = None,
        manufacturer: str | None = None,
    ) -> str:
        e = entry or self.entry
        d = self.devices.async_get_or_create(
            config_entry_id=e.entry_id,
            identifiers={identifiers or (e.domain, name)},
            name=name,
            manufacturer=manufacturer,
        )
        self.devices.async_update_device(
            d.id, area_id=self.area(area) if area else None, labels={self.label(x) for x in labels}
        )
        return d.id

    def entity(
        self,
        entity_id: str,
        state: str,
        *,
        device: str | None = None,
        area: str | None = None,
        attrs: dict[str, Any] | None = None,
        device_class: str | None = None,
        labels: tuple[str, ...] = (),
        category: str | None = None,
        hidden: bool = False,
        translation_key: str | None = None,
        unique_id: str | None = None,
        entry: MockConfigEntry | None = None,
        platform: str | None = None,
    ) -> str:
        domain, object_id = entity_id.split(".", 1)
        e = entry or self.entry
        reg = self.entities.async_get_or_create(
            domain,
            platform or e.domain,
            unique_id or entity_id,
            suggested_object_id=object_id,
            config_entry=e,
            device_id=device,
            original_device_class=device_class,
            translation_key=translation_key,
            entity_category=EntityCategory(category) if category else None,
        )
        if reg.entity_id != entity_id:
            reg = self.entities.async_update_entity(reg.entity_id, new_entity_id=entity_id)
        self.entities.async_update_entity(
            entity_id,
            area_id=self.area(area) if area else None,
            labels={self.label(x) for x in labels},
            hidden_by=er.RegistryEntryHider.USER if hidden else None,
        )
        attributes = dict(attrs or {})
        if device_class:
            attributes.setdefault("device_class", device_class)
        self.hass.states.async_set(entity_id, state, attributes)
        return entity_id

    def person(self, object_id: str, name: str, state: str = "home", user_id: str | None = None) -> str:
        entity_id = f"person.{object_id}"
        self.hass.states.async_set(
            entity_id,
            state,
            {"friendly_name": name, "user_id": user_id, "device_trackers": [f"device_tracker.{object_id}_phone"]},
        )
        return entity_id

    def set(self, entity_id: str, state: str, attrs: dict[str, Any] | None = None) -> None:
        current = self.hass.states.get(entity_id)
        attributes = dict(current.attributes) if current else {}
        attributes.update(attrs or {})
        self.hass.states.async_set(entity_id, state, attributes)


def standard_home(hass: HomeAssistant) -> Home:
    """Two floors, a few rooms, lights, sensors, a leak sensor, a battery device and two people."""
    h = Home(hass)
    h.area("Kitchen", floor="Ground")
    h.area("Living room", floor="Ground")
    h.area("Bedroom", floor="First")
    lamp = h.device("Ceiling lamp", area="Living room")
    h.entity("light.ceiling", "off", device=lamp, attrs={"friendly_name": "Ceiling lamp"})
    plug = h.device("Coffee plug", area="Kitchen")
    h.entity("switch.coffee", "off", device=plug, device_class="outlet", attrs={"friendly_name": "Coffee plug"})
    leak = h.device("Sink leak sensor", area="Kitchen")
    h.entity(
        "binary_sensor.sink_leak", "off", device=leak, device_class="moisture", attrs={"friendly_name": "Sink leak"}
    )
    h.entity(
        "sensor.sink_leak_battery",
        "80",
        device=leak,
        device_class="battery",
        category="diagnostic",
        attrs={"unit_of_measurement": "%", "friendly_name": "Sink leak battery"},
    )
    climate = h.device("Bedroom sensor", area="Bedroom")
    h.entity(
        "sensor.bedroom_temperature",
        "21.5",
        device=climate,
        device_class="temperature",
        attrs={"unit_of_measurement": "°C", "friendly_name": "Bedroom temperature"},
    )
    h.entity(
        "binary_sensor.bedroom_window",
        "off",
        device=climate,
        device_class="window",
        attrs={"friendly_name": "Bedroom window"},
    )
    h.person("anna", "Anna")
    h.person("ben", "Ben", state="not_home")
    return h
