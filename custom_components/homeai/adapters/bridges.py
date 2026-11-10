"""Hubs and bridges: when a hub goes offline, the devices behind it are one situation, not dozens.

A bridge is a connectivity entity of a device that other devices connect through (`via_device`), the
Zigbee2MQTT bridge state, or an entity the administrator listed in `adapters.bridge_entities`. Its signal
suppresses `via:<hub device>` (and `zigbee` for Zigbee2MQTT), so unavailable devices behind it are folded in.
Repair: restart the Zigbee2MQTT add-on when its slug is set, otherwise reload the hub's integration.
"""

from __future__ import annotations

from typing import Any

from ..signals.base import Category, DetectionContext, Detector, Need, Signal
from ..signals.detectors.util import held_for, setting, state
from ..world import Role

OFFLINE = frozenset({"off", "offline", "disconnected", "unavailable"})


def _is_z2m(ctx: DetectionContext, device_id: str | None) -> bool:
    device = ctx.world.devices.get(device_id) if device_id else None
    return bool(device and any(d == "mqtt" and str(i).startswith("zigbee2mqtt_bridge") for d, i in device.identifiers))


class BridgeDetector(Detector):
    key = "bridges"
    roles = (Role.CONNECTIVITY,)

    def candidates(self, ctx: DetectionContext) -> set[str]:
        world = ctx.world
        found = {e for e in ctx.settings.get("adapters.bridge_entities") if e in world.entities}
        if not ctx.settings.get("adapters.auto_bridges"):
            return found
        hubs = {d.via_device_id for d in world.devices.values() if d.via_device_id}
        for entity_id in world.with_role(Role.CONNECTIVITY):
            info = world.entity(entity_id)
            if info and info.device_id and (info.device_id in hubs or _is_z2m(ctx, info.device_id)):
                found.add(entity_id)
        for entity_id, info in world.entities.items():
            if info.domain == "sensor" and _is_z2m(ctx, info.device_id) and entity_id.endswith("bridge_state"):
                found.add(entity_id)
        return found

    def watched_entities(self, ctx: DetectionContext) -> set[str]:
        return self.candidates(ctx)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out: list[Signal] = []
        for entity_id in sorted(self.candidates(ctx)):
            s = state(ctx, entity_id)
            if s is None or s.state not in OFFLINE:
                continue
            if not held_for(s, ctx.now, float(setting(ctx, "adapters.bridge_minutes", entity_id))):
                continue
            info = ctx.world.entity(entity_id)
            device_id = info.device_id if info else None
            z2m = _is_z2m(ctx, device_id)
            suppresses = {f"via:{device_id}"} if device_id else set()
            if z2m:
                suppresses.add("zigbee")
            repair: dict[str, Any] | None = None
            addon = ctx.settings.get("adapters.zigbee2mqtt_addon")
            if z2m and addon:
                repair = {"playbook": "restart_addon", "addon": addon}
            elif (
                device_id
                and (entry := ctx.world.devices[device_id].config_entry_id)
                and ctx.settings.get("adapters.bridge_reload")
            ):
                repair = {"playbook": "reload_entry", "entry_id": entry}
            name = ctx.world.device_name(device_id) if device_id else ctx.world.display_name(entity_id)
            out.append(
                Signal(
                    id=f"bridge_offline:{device_id or entity_id}",
                    detector=self.key,
                    kind="bridge_offline",
                    category=Category.SYSTEM,
                    severity=int(setting(ctx, "adapters.bridge_severity", entity_id)),
                    entities=(entity_id,),
                    device_id=device_id,
                    area_id=info.area_id if info else None,
                    since=s.last_changed,
                    data={"name": name, "where": ctx.world.area_name(info.area_id if info else None)},
                    need=Need.ADMIN,
                    root=f"bridge:{device_id or entity_id}",
                    suppresses=frozenset(suppresses),
                    repair=repair,
                )
            )
        return out


class Adapters:
    """Stage that adds adapter detectors to the signal hub."""

    def __init__(self, runtime: Any) -> None:
        self.rt = runtime

    async def async_setup(self) -> None:
        hub = self.rt.module("signals")
        if hub is not None:
            hub.add_detector(BridgeDetector())

    async def async_unload(self) -> None:
        return None
