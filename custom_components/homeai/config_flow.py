"""Config flow for HomeAI."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, NAME


class HomeAIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up HomeAI. Only one instance is allowed (`single_config_entry` in the manifest)."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm adding HomeAI."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user")
