"""Shared base for HomeAI entities: one service device, translated names, updates from the runtime."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME, VERSION


def device_info() -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, "homeai")},
        name=NAME,
        manufacturer="HomeAI",
        model="Home intelligence",
        sw_version=VERSION,
        entry_type=DeviceEntryType.SERVICE,
    )


async def check_admin(entity: Entity, rt: Any, setting: str) -> tuple[str | None, bool]:
    """(user name, is admin) of the caller; raises Unauthorized when a non-administrator changes an admin setting."""
    from homeassistant.exceptions import Unauthorized

    user_id = entity._context.user_id if entity._context else None
    if not user_id:
        return None, True  # automations and scripts (created by administrators)
    user = await entity.hass.auth.async_get_user(user_id)
    admin = bool(user and user.is_admin)
    if rt.settings.registry[setting].admin_only and not admin:
        raise Unauthorized(context=entity._context, entity_id=entity.entity_id)
    return (user.name if user else None), admin


class HomeAIEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: Any, key: str) -> None:
        self.rt = runtime
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_device_info = device_info()
        self.entity_id = f"{self.platform_domain}.{DOMAIN}_{key}"

    platform_domain = "sensor"
