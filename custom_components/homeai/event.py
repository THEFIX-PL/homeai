"""Event entities: situation lifecycle and notifications, for automations and custom displays."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.event import EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_NOTIFICATION, EVENT_SITUATION
from .entity import HomeAIEntity
from .situations.model import EVENTS


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    async_add_entities([SituationEvent(rt), NotificationEvent(rt)])


class _BusEvent(HomeAIEntity, EventEntity):
    platform_domain = "event"
    bus_event = ""
    type_field = ""

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hass.bus.async_listen(self.bus_event, self._on_event))

    @callback
    def _on_event(self, event: Event) -> None:
        etype = str(event.data.get(self.type_field, ""))
        if etype not in self.event_types:
            return
        self._trigger_event(etype, {k: v for k, v in event.data.items() if k != self.type_field})
        self.async_write_ha_state()


class SituationEvent(_BusEvent):
    bus_event = EVENT_SITUATION
    type_field = "event"
    _attr_event_types: ClassVar[list[str]] = list(EVENTS)

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "situation")


class NotificationEvent(_BusEvent):
    """Fired for notification steps with the `event` channel: build custom displays (LED matrix, tablets…)."""

    bus_event = EVENT_NOTIFICATION
    type_field = "state"
    _attr_event_types: ClassVar[list[str]] = ["active", "cleared"]

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "notification")
