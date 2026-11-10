"""HomeAI: home intelligence for Home Assistant.

One config entry runs one `HomeAIRuntime`: world model, detection, situations, notifications, policy, actions,
scheduler, memory and the optional AI tiers. Everything is configured from the UI (setup wizard, options,
subentries for AI tiers and the settings panel).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api.services import async_register_services
from .api.websocket import async_register as async_register_websocket
from .const import DOMAIN
from .platforms import PLATFORMS
from .runtime import HomeAIRuntime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HomeAIConfigEntry = ConfigEntry[HomeAIRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register things that live as long as Home Assistant: WebSocket commands and services."""
    async_register_websocket(hass)
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomeAIConfigEntry) -> bool:
    """Set up HomeAI from a config entry."""
    runtime = HomeAIRuntime(hass, entry)
    entry.runtime_data = runtime
    await runtime.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: HomeAIConfigEntry) -> None:
    """Options or subentries (AI tiers) changed: reload so modules pick them up."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HomeAIConfigEntry) -> bool:
    """Unload a HomeAI config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_unload()
    return ok
