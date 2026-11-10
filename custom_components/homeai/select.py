"""The autonomy slider: one setting over the whole policy, from only observing to acting boldly."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HomeAIEntity, check_admin

SELECTS = {"autonomy": "policy.slider"}


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    async_add_entities(
        [SettingSelect(rt, key, setting) for key, setting in SELECTS.items() if setting in rt.settings.registry]
    )


class SettingSelect(HomeAIEntity, SelectEntity):
    """A choice setting as a select. Changing it needs an administrator (also through services)."""

    platform_domain = "select"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: Any, key: str, setting: str) -> None:
        super().__init__(runtime, key)
        self._setting = setting
        self._attr_options = list(runtime.settings.registry[setting].options)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rt.settings.listen(self._setting, self._changed))

    @callback
    def _changed(self, _key: str) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        return str(self.rt.settings.get(self._setting))

    async def async_select_option(self, option: str) -> None:
        name, admin = await check_admin(self, self.rt, self._setting)
        self.rt.settings.set(self._setting, option, user=name, confirmed=True, is_admin=admin)
