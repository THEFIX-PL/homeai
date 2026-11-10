"""HomeAI: home intelligence for Home Assistant.

This is the project skeleton. The world model, signals, situations, policy, executor,
notifications and AI tiers arrive in later milestones (see README.md, "Roadmap").
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HomeAIConfigEntry = ConfigEntry[None]


async def async_setup_entry(hass: HomeAssistant, entry: HomeAIConfigEntry) -> bool:
    """Set up HomeAI from a config entry."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeAIConfigEntry) -> bool:
    """Unload a HomeAI config entry."""
    return True
