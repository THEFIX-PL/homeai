"""Setup wizard, options and single instance."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homeai.const import CONF_INITIAL_SETTINGS, DOMAIN, NAME


async def test_wizard_without_people(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"language": "pl", "privacy": "minimal"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    initial = result["data"][CONF_INITIAL_SETTINGS]
    assert initial["general.language"] == "pl" and initial["privacy.level"] == "minimal"


async def test_wizard_with_people_applies_roles(hass: HomeAssistant) -> None:
    hass.states.async_set("person.anna", "home", {"friendly_name": "Anna"})
    hass.states.async_set("person.guest", "not_home", {"friendly_name": "Guest"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"language": "auto", "privacy": "standard"}
    )
    assert result["step_id"] == "people"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"person.anna": "admin", "person.guest": "guest"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()
    rt = entry.runtime_data
    from custom_components.homeai.settings import Target

    assert rt.settings.get("presence.role", Target(person_id="person.anna")) == "admin"
    assert rt.settings.get("presence.role", Target(person_id="person.guest")) == "guest"
    assert entry.data["initial_settings_applied"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_only_one_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_quick_settings(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"general_language": "pl", "privacy_level": "standard"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.runtime_data.settings.get("general.language") == "pl"
