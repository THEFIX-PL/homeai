"""The HomeAI panel in the sidebar and the Lovelace cards (one module served by the integration)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import LOGGER, NAME, PANEL_URL, STATIC_URL, VERSION

FILE = "homeai-panel.js"
DATA_STATIC = "homeai_static_registered"


async def async_setup_panel(hass: HomeAssistant, rt: Any) -> None:
    path = Path(__file__).parent / "frontend"
    if not (path / FILE).exists():
        LOGGER.warning("HomeAI panel is not built (%s missing)", FILE)
        return
    module_url = f"{STATIC_URL}/{FILE}?v={VERSION}"
    if not hass.data.get(DATA_STATIC) and getattr(hass, "http", None) is not None:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(path), cache_headers=False)])
        hass.data[DATA_STATIC] = True
        if "frontend" in hass.config.components:
            from homeassistant.components.frontend import add_extra_js_url

            # Makes the cards available on dashboards: as a module for current browsers, and as a plain script
            # for browsers Home Assistant serves its legacy build to (e.g. iOS before 18.1).
            add_extra_js_url(hass, module_url)
            add_extra_js_url(hass, module_url, es5=True)
    if "frontend" not in hass.config.components or not rt.settings.get("general.panel_sidebar"):
        return
    from homeassistant.components import panel_custom

    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="homeai-panel",
            sidebar_title=NAME,
            sidebar_icon="mdi:home-heart",
            module_url=module_url,
            require_admin=bool(rt.settings.get("general.panel_admin_only")),
            config={},
        )
    except ValueError:
        LOGGER.debug("HomeAI panel already registered")


def async_remove_panel(hass: HomeAssistant) -> None:
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import async_remove_panel

    async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
