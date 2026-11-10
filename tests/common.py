"""Shared helpers: set up HomeAI with chosen settings and drive time."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.homeai.const import DOMAIN

FAST = {
    "general.startup_grace": 0,
    "situations.min_duration": 0,
    "situations.min_duration_security": 0,
    "situations.min_duration_damage": 0,
    "situations.close_after": 0,
    "notify.digest_enabled": False,
    "presence.sleep_sources": ["helper"],
}


async def setup_homeai(
    hass: HomeAssistant,
    settings: dict[str, Any] | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    *,
    ready: bool = True,
    subentries: list[dict[str, Any]] | None = None,
) -> Any:
    """Set up HomeAI; returns the runtime. `overrides` maps scope keys ("person:person.anna") to settings."""
    initial: dict[str, Any] = {**FAST, **(settings or {})}
    if overrides:
        initial["overrides"] = overrides
    from homeassistant.config_entries import ConfigSubentryData

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"initial_settings": initial},
        subentries_data=[
            ConfigSubentryData(data=sub, subentry_type="tier", title=f"{sub['tier']} {sub['model']}", unique_id=None)
            for sub in subentries or []
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    rt = entry.runtime_data
    rt.ready = ready
    return rt


def phones(hass: HomeAssistant, *names: str) -> list[ServiceCall]:
    """Fake `notify.mobile_app_<name>` services; all calls land in one list."""
    calls: list[ServiceCall] = []

    @callback
    def record(call: ServiceCall) -> None:
        calls.append(call)

    for name in names:
        hass.services.async_register("notify", f"mobile_app_{name}", record)
    return calls


def phone_targets(*people: str) -> dict[str, dict[str, Any]]:
    """Per-person notify targets: person.<name> → notify.mobile_app_<name>."""
    return {
        f"person:person.{p}": {"notify.targets": [f"notify.mobile_app_{p}"], "notify.discover_apps": False}
        for p in people
    }


async def settle(hass: HomeAssistant, rt: Any) -> None:
    """Evaluate every detector and run the situation engine once."""
    rt.module("signals").evaluate()
    await hass.async_block_till_done()
    await rt.module("situations").process()
    await hass.async_block_till_done()


async def advance(hass: HomeAssistant, **delta: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(**delta))
    await hass.async_block_till_done()
