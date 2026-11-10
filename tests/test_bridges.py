"""Hubs and bridges: a hub offline explains the devices behind it."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .common import setup_homeai
from .home import standard_home


async def test_hub_offline_folds_child_devices(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    hub = home.device("Hue bridge", area="Living room")
    home.entity("binary_sensor.hue_bridge_connected", "on", device=hub, device_class="connectivity")
    bulb = home.device("Hall bulb", area="Living room")
    dr.async_get(hass).async_update_device(bulb, via_device_id=hub)
    home.entity("light.hall", "on", device=bulb)
    rt = await setup_homeai(hass, {"adapters.bridge_minutes": 1, "detectors.availability.minutes": 1})
    hub_signals = rt.module("signals")

    home.set("binary_sensor.hue_bridge_connected", "off")
    home.set("light.hall", "unavailable")
    freezer.tick(timedelta(minutes=2))
    hub_signals.evaluate()
    bridge = hub_signals.signals[f"bridge_offline:{hub}"]
    assert bridge.suppresses == frozenset({f"via:{hub}"}) and bridge.repair["playbook"] == "reload_entry"
    child = next(s for s in hub_signals.signals.values() if s.kind == "device_unavailable")
    assert f"via:{hub}" in child.tags

    engine = rt.module("situations")
    await engine.process()
    [s] = engine.open()
    assert s.kind == "bridge_offline" and child.id in s.suppressed


async def test_zigbee2mqtt_bridge_restarts_addon(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    home = standard_home(hass)
    mqtt = MockConfigEntry(domain="mqtt", title="MQTT")
    mqtt.add_to_hass(hass)
    bridge = home.device("Zigbee2MQTT Bridge", identifiers=("mqtt", "zigbee2mqtt_bridge_0x00"), entry=mqtt)
    home.entity("binary_sensor.z2m_connection_state", "on", device=bridge, device_class="connectivity", entry=mqtt)
    rt = await setup_homeai(hass, {"adapters.zigbee2mqtt_addon": "45df7312_zigbee2mqtt", "adapters.bridge_minutes": 0})
    home.set("binary_sensor.z2m_connection_state", "off")
    signal = rt.module("signals").evaluate()[f"bridge_offline:{bridge}"]
    assert "zigbee" in signal.suppresses
    assert signal.repair == {"playbook": "restart_addon", "addon": "45df7312_zigbee2mqtt"}
