"""Configuration switches that mirror HomeAI settings, for automations and dashboards."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import HomeAIEntity, check_admin

SWITCHES = {
    "notifications_paused": "notify.paused",
    "ai": "ai.enabled",
    "vacation": "presence.vacation_mode",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    from .platform_extras import extra_entities

    async_add_entities(
        [SettingSwitch(rt, key, setting) for key, setting in SWITCHES.items() if setting in rt.settings.registry]
        + extra_entities(rt, "switch")
    )


class SettingSwitch(HomeAIEntity, SwitchEntity):
    """A boolean setting as a switch. Only administrators may change admin-only settings."""

    platform_domain = "switch"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: Any, key: str, setting: str) -> None:
        super().__init__(runtime, key)
        self._setting = setting

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rt.settings.listen(self._setting, self._changed))

    @callback
    def _changed(self, _key: str) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return bool(self.rt.settings.get(self._setting))

    async def _set(self, value: bool) -> None:
        name, admin = await check_admin(self, self.rt, self._setting)
        self.rt.settings.set(self._setting, value, user=name, confirmed=True, is_admin=admin)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
