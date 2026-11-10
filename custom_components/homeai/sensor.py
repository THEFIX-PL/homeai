"""Sensors: open situations (count and list)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HomeAIEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    entities: list[SensorEntity] = []
    if rt.module("situations") is not None:
        entities.append(SituationsSensor(rt))
    from .platform_extras import extra_entities

    entities += extra_entities(rt, "sensor")
    async_add_entities(entities)


class SituationsSensor(HomeAIEntity, SensorEntity):
    """Number of open situations that need attention (severity ≥ 1, not acknowledged); attribute: the list."""

    platform_domain = "sensor"
    _unrecorded_attributes = frozenset({"situations"})

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "situations")

    async def async_added_to_hass(self) -> None:
        engine = self.rt.module("situations")
        self.async_on_remove(engine.listen(self._changed))
        self.async_on_remove(self.rt.on_tick(lambda _now: self.async_write_ha_state()))

    @callback
    def _changed(self, _event: str, _situation: Any) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        engine = self.rt.module("situations")
        return sum(1 for s in engine.open() if s.severity >= 1 and not s.muted())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        engine = self.rt.module("situations")
        lang = self.rt.language
        return {
            "situations": [
                {
                    "id": s.id,
                    "title": s.title(lang),
                    "severity": s.severity,
                    "category": s.category,
                    "who": s.assessment.get("who"),
                    "phase": str(s.phase),
                    "since": (s.opened_at or s.first_seen).isoformat(timespec="seconds"),
                    "acknowledged": s.acked_at is not None,
                    "repairing": s.repair.get("status") in ("waiting", "trying"),
                }
                for s in engine.open()
            ]
        }
