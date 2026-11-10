"""A large home stays fast: building the world, evaluating every detector and running the situation engine."""

from __future__ import annotations

import time

from homeassistant.core import HomeAssistant

from .common import settle, setup_homeai
from .home import Home

DEVICES = 400  # four entities each, plus their areas: about 1,600 entities


def big_home(hass: HomeAssistant) -> Home:
    home = Home(hass)
    for floor in range(4):
        for room in range(10):
            home.area(f"Room {floor}-{room}", floor=f"Floor {floor}")
    for i in range(DEVICES):
        area = f"Room {i % 4}-{i % 10}"
        device = home.device(f"Device {i}", area=area)
        home.entity(f"light.l{i}", "off", device=device, attrs={"friendly_name": f"Light {i}"})
        home.entity(
            f"sensor.t{i}",
            str(20 + i % 5),
            device=device,
            device_class="temperature",
            attrs={"unit_of_measurement": "°C", "friendly_name": f"Temperature {i}"},
        )
        home.entity(
            f"sensor.b{i}",
            str(5 if i % 50 == 0 else 90),  # a few low batteries
            device=device,
            device_class="battery",
            category="diagnostic",
            attrs={"unit_of_measurement": "%", "friendly_name": f"Battery {i}"},
        )
        home.entity(
            f"binary_sensor.w{i}",
            "off",
            device=device,
            device_class="window",
            attrs={"friendly_name": f"Window {i}"},
        )
    home.person("anna", "Anna")
    return home


async def test_large_home_is_fast(hass: HomeAssistant) -> None:
    big_home(hass)
    started = time.perf_counter()
    rt = await setup_homeai(hass)
    setup = time.perf_counter() - started
    assert len(rt.world.entities) >= DEVICES * 4

    started = time.perf_counter()
    for _ in range(5):
        await settle(hass, rt)
    per_pass = (time.perf_counter() - started) / 5

    batteries = [s for s in rt.module("situations").open() if s.kind == "battery_low"]
    assert batteries and len(batteries) == 1  # eight low batteries, one grouped situation
    # Generous limits for slow CI machines; locally a pass takes a few tens of milliseconds.
    assert setup < 20, f"setup took {setup:.2f}s"
    assert per_pass < 1.0, f"a detector pass took {per_pass:.3f}s"

    # A burst of state changes is coalesced, not evaluated once per change.
    started = time.perf_counter()
    for i in range(DEVICES):
        hass.states.async_set(f"sensor.t{i}", "22.5", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    await settle(hass, rt)
    assert time.perf_counter() - started < 5
