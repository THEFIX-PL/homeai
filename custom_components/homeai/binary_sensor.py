"""Binary sensor: something in the home needs attention now."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HomeAIEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    if rt.module("situations") is not None:
        async_add_entities([AttentionSensor(rt)])


class AttentionSensor(HomeAIEntity, BinarySensorEntity):
    """On while an open situation of severity 2 or more is not acknowledged."""

    platform_domain = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "attention")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rt.module("situations").listen(self._changed))
        self.async_on_remove(self.rt.on_tick(lambda _now: self.async_write_ha_state()))

    @callback
    def _changed(self, _event: str, _situation: Any) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return any(s.severity >= 2 and not s.muted() for s in self.rt.module("situations").open())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        top = [s for s in self.rt.module("situations").open() if s.severity >= 2 and not s.muted()]
        return {"highest_severity": max((s.severity for s in top), default=None)}
