"""The panel module is served by the integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .common import setup_homeai
from .home import standard_home


async def test_panel_module_is_served(hass: HomeAssistant, hass_client) -> None:
    standard_home(hass)
    await setup_homeai(hass)
    client = await hass_client()
    resp = await client.get("/homeai_static/homeai-panel.js")
    assert resp.status == 200
    body = await resp.text()
    assert "homeai-panel" in body and "homeai-situations-card" in body
