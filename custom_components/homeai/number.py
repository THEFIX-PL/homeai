"""Number settings for automations and dashboards (the monthly AI budget)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HomeAIEntity, check_admin

NUMBERS = {"ai_budget_monthly": "ai.budget_monthly"}


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    async_add_entities(
        [SettingNumber(rt, key, setting) for key, setting in NUMBERS.items() if setting in rt.settings.registry]
    )


class SettingNumber(HomeAIEntity, NumberEntity):
    platform_domain = "number"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime: Any, key: str, setting: str) -> None:
        super().__init__(runtime, key)
        self._setting = setting
        spec = runtime.settings.registry[setting]
        self._attr_native_min_value = float(spec.min or 0)
        self._attr_native_max_value = float(spec.max or 1000)
        self._attr_native_step = float(spec.step or 1)
        self._attr_native_unit_of_measurement = "USD" if spec.unit == "$" else spec.unit

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rt.settings.listen(self._setting, self._changed))

    @callback
    def _changed(self, _key: str) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return float(self.rt.settings.get(self._setting))

    async def async_set_native_value(self, value: float) -> None:
        name, admin = await check_admin(self, self.rt, self._setting)
        self.rt.settings.set(self._setting, value, user=name, confirmed=True, is_admin=admin)
