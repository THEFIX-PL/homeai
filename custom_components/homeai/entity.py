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
