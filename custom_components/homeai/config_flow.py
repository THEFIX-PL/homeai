"""Config flow for HomeAI: a short setup wizard, quick options, and AI tiers as subentries.

The wizard only asks what HomeAI cannot discover: the household's language, how much data may go to cloud AI,
and each person's role. Everything else has defaults and lives in the settings panel.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
import voluptuous as vol

from .const import CONF_INITIAL_SETTINGS, DOMAIN, NAME
from .settings.definitions import ROLES

LANGUAGES = ["auto", "en", "pl"]
PRIVACY = ["standard", "minimal", "full"]


def _select(options: list[str], key: str) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=options, translation_key=key, mode=SelectSelectorMode.DROPDOWN))


class HomeAIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up HomeAI. Only one instance is allowed (`single_config_entry` in the manifest)."""

    VERSION = 1

    def __init__(self) -> None:
        self._initial: dict[str, Any] = {"overrides": {}}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Language and privacy for cloud AI."""
        if user_input is not None:
            self._initial["general.language"] = user_input["language"]
            self._initial["privacy.level"] = user_input["privacy"]
            if self._persons():
                return await self.async_step_people()
            return self._finish()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("language", default="auto"): _select(LANGUAGES, "language"),
                    vol.Required("privacy", default="standard"): _select(PRIVACY, "privacy"),
                }
            ),
        )

    async def async_step_people(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Role of each person: administrator, member, guest or ignored."""
        persons = self._persons()
        if user_input is not None:
            for entity_id, _name in persons:
                role = user_input.get(entity_id, "member")
                if role != "member":
                    self._initial["overrides"][f"person:{entity_id}"] = {"presence.role": role}
            return self._finish()
        schema = {
            vol.Required(entity_id, default=await self._default_role(entity_id)): _select(list(ROLES), "role")
            for entity_id, _name in persons
        }
        names = ", ".join(f"{name} ({entity_id})" for entity_id, name in persons)
        return self.async_show_form(
            step_id="people", data_schema=vol.Schema(schema), description_placeholders={"people": names}
        )

    def _persons(self) -> list[tuple[str, str]]:
        return sorted((s.entity_id, s.name) for s in self.hass.states.async_all("person"))

    async def _default_role(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        user_id = state.attributes.get("user_id") if state else None
        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        return "admin" if user is not None and user.is_admin else "member"

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title=NAME, data={CONF_INITIAL_SETTINGS: self._initial})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HomeAIOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        from .ai.subentry import SUBENTRY_FLOWS

        return dict(SUBENTRY_FLOWS)


class HomeAIOptionsFlow(OptionsFlow):
    """Most common settings; everything else is in the HomeAI panel."""

    QUICK = ("general.language", "privacy.level", "notify.paused")

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        settings = runtime.settings
        keys = [k for k in self.QUICK if k in settings.registry]
        if user_input is not None:
            user = self.context.get("user_id")
            for key in keys:
                field = key.replace(".", "_")
                if field in user_input:
                    settings.set(key, user_input[field], user=user, confirmed=True)
            return self.async_create_entry(data=dict(self.config_entry.options))
        schema: dict[Any, Any] = {}
        for key in keys:
            setting = settings.registry[key]
            current = settings.get(key)
            field = key.replace(".", "_")  # translation keys cannot contain dots
            if setting.options:
                schema[vol.Required(field, default=current)] = _select(list(setting.options), field)
            else:
                schema[vol.Required(field, default=current)] = bool if setting.type == "bool" else str
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
