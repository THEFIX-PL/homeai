"""AI tiers as config subentries: P1 (everyday brain), P2 (investigation), P3 (arbiter).

Several subentries may serve the same tier: they are tried in order of `priority` (lower first), so a local
model can be the first choice with a cloud model as its fallback.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from ..const import LOGGER
from .pricing import DEFAULT_EFFORT, DEFAULT_MODELS, PRICES

TIERS = ("p1", "p2", "p3")
PROVIDERS = ("anthropic", "openai_compatible")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
PRIVACY = ("default", "minimal", "standard", "full")
# Optional limits per connection: (field, min, max, step, unit). Empty: the HomeAI settings apply.
LIMITS = (
    ("max_tokens", 256, 64000, 256, "tokens"),
    ("timeout", 10, 3600, 5, "s"),
    ("budget_daily", 0.01, 1000, 0.01, "$"),
)


def _select(key: str, options: tuple[str, ...] | list[str], *, custom: bool = False) -> SelectSelector:
    if custom:  # free text with suggestions (model names change faster than translations)
        return SelectSelector(
            SelectSelectorConfig(options=list(options), mode=SelectSelectorMode.DROPDOWN, custom_value=True)
        )
    return SelectSelector(
        SelectSelectorConfig(options=list(options), translation_key=key, mode=SelectSelectorMode.DROPDOWN)
    )


def details_schema(provider: str, tier: str, current: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if provider == "openai_compatible":
        fields[vol.Required("base_url", default=current.get("base_url", "http://localhost:11434/v1"))] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
        fields[vol.Required("model", default=current.get("model", "qwen3:4b"))] = TextSelector()
        fields[vol.Optional("api_key", default=current.get("api_key", ""))] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    else:
        fields[vol.Required("api_key", default=current.get("api_key", ""))] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
        fields[vol.Required("model", default=current.get("model", DEFAULT_MODELS[tier]))] = _select(
            "model", sorted(PRICES), custom=True
        )
        fields[vol.Required("effort", default=current.get("effort", DEFAULT_EFFORT[tier]))] = _select("effort", EFFORTS)
        fields[vol.Required("fallbacks", default=current.get("fallbacks", True))] = BooleanSelector()
    fields[vol.Required("privacy", default=current.get("privacy", "default"))] = _select("privacy_tier", PRIVACY)
    fields[vol.Required("priority", default=current.get("priority", 1))] = NumberSelector(
        NumberSelectorConfig(min=1, max=9, step=1, mode=NumberSelectorMode.BOX)
    )
    for key in ("price_input", "price_output"):
        fields[vol.Optional(key, description={"suggested_value": current.get(key)})] = NumberSelector(
            NumberSelectorConfig(min=0, max=1000, step=0.01, mode=NumberSelectorMode.BOX, unit_of_measurement="$/Mtok")
        )
    for key, low, high, step, unit in LIMITS:
        fields[vol.Optional(key, description={"suggested_value": current.get(key)})] = NumberSelector(
            NumberSelectorConfig(min=low, max=high, step=step, mode=NumberSelectorMode.BOX, unit_of_measurement=unit)
        )
    return vol.Schema(fields)


async def validate(hass: Any, data: dict[str, Any]) -> str | None:
    """Check the connection without spending tokens; returns an error key or None."""
    from .providers.base import AIError
    from .tiers import TierConfig, build_provider

    try:
        provider = await build_provider(hass, TierConfig.from_data("check", data))
        await provider.check()
    except AIError as err:
        return str(err) if str(err) in ("invalid_auth", "cannot_connect", "unknown_model") else "cannot_connect"
    except Exception:
        LOGGER.exception("AI tier check failed")
        return "cannot_connect"
    return None


class TierSubentryFlow(ConfigSubentryFlow):
    """Add or change an AI tier."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._data = {"tier": user_input["tier"], "provider": user_input["provider"]}
            return await self.async_step_details()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("tier", default="p1"): _select("tier", TIERS),
                    vol.Required("provider", default="anthropic"): _select("provider", PROVIDERS),
                }
            ),
        )

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._data, **user_input, "priority": int(user_input.get("priority", 1))}
            if (error := await validate(self.hass, data)) is None:
                title = f"{data['tier'].upper()} · {data['model']}"
                if self.source == "reconfigure":
                    return self.async_update_and_abort(
                        self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
                    )
                return self.async_create_entry(title=title, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="details",
            data_schema=details_schema(
                self._data["provider"], self._data["tier"], {**self._data, **(user_input or {})}
            ),
            errors=errors,
            description_placeholders={
                "tier": self._data["tier"].upper(),
                "example_url": "http://ollama.local:11434/v1",
            },
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._data = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_details()


SUBENTRY_FLOWS: dict[str, type[ConfigSubentryFlow]] = {"tier": TierSubentryFlow}
