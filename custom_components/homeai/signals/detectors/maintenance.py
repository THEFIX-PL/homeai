"""Maintenance: batteries, consumables, plants, devices reporting a problem and sensors that stopped reporting."""

from __future__ import annotations

from datetime import timedelta

from ...world import Role
from ..base import Category, DetectionContext, Detector, Need, Signal
from .util import UNAVAILABLE, area_of, clock, critical, device_of, name, setting, state, where


class BatteryDetector(Detector):
    """Battery level at or below the threshold, or a binary “battery low”, one signal per device."""

    key = "battery"
    roles = (Role.BATTERY, Role.BATTERY_LOW)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        found: dict[str, tuple[str, float | None]] = {}
        for entity_id in sorted(ctx.world.with_role(Role.BATTERY)):
            value = ctx.world.value(entity_id)
            info = ctx.world.entity(entity_id)
            if value is None or info is None or (info.unit and info.unit != "%"):
                continue
            if value <= float(setting(ctx, "detectors.battery.threshold", entity_id)):
                key = info.device_id or entity_id
                if key not in found or (found[key][1] or 100) > value:
                    found[key] = (entity_id, value)
        for entity_id in sorted(ctx.world.with_role(Role.BATTERY_LOW)):
            s = state(ctx, entity_id)
            info = ctx.world.entity(entity_id)
            if s is not None and s.state == "on" and info is not None:
                found.setdefault(info.device_id or entity_id, (entity_id, None))
        out = []
        for key, (entity_id, level) in found.items():
            device_id = device_of(ctx, entity_id)
            device_name = ctx.world.device_name(device_id) if device_id else name(ctx, entity_id)
            device_entities = ctx.world.of_device(device_id) if device_id else {entity_id}
            protects = any(
                ctx.world.entity(e)
                and ctx.world.entity(e).roles & {Role.SMOKE, Role.GAS, Role.CARBON_MONOXIDE, Role.LEAK}
                for e in device_entities
            )
            severity = int(setting(ctx, "detectors.battery.severity", entity_id))
            if protects or critical(ctx, entity_id):
                severity = max(severity, int(setting(ctx, "detectors.battery.safety_severity", entity_id)))
            area = area_of(ctx, entity_id)
            out.append(
                Signal(
                    id=f"battery:{key}",
                    detector=self.key,
                    kind="battery_low",
                    category=Category.MAINTENANCE,
                    severity=severity,
                    entities=(entity_id,),
                    device_id=device_id,
                    area_id=area,
                    data={
                        "name": device_name,
                        "where": where(ctx, area_id=area),
                        "level": f"{round(level)}%" if level is not None else "",
                    },
                    need=Need.MEMBER,
                    root="batteries" if setting(ctx, "detectors.battery.group") else None,
                )
            )
        return out


class ConsumableDetector(Detector):
    """Filters, brushes and other consumables with little life left (percent or hours remaining)."""

    key = "consumables"
    roles = (Role.CONSUMABLE,)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out = []
        for entity_id in sorted(ctx.world.with_role(Role.CONSUMABLE)):
            value = ctx.world.value(entity_id)
            info = ctx.world.entity(entity_id)
            if value is None or info is None:
                continue
            limit = float(setting(ctx, "detectors.consumables.percent", entity_id)) if info.unit == "%" else 0.0
            inverted = entity_id in set(ctx.settings.get("detectors.consumables.used_up_entities"))
            due = value >= 100 - limit if inverted else value <= limit
            if not due:
                continue
            area = area_of(ctx, entity_id)
            out.append(
                Signal(
                    id=f"consumable:{entity_id}",
                    detector=self.key,
                    kind="consumable_low",
                    category=Category.MAINTENANCE,
                    severity=int(setting(ctx, "detectors.consumables.severity", entity_id)),
                    entities=(entity_id,),
                    device_id=info.device_id,
                    area_id=area,
                    data={"name": name(ctx, entity_id), "where": where(ctx, area_id=area)},
                    need=Need.MEMBER,
                    root="consumables",
                )
            )
        return out


class ProblemDetector(Detector):
    """Binary sensors with the `problem` device class that are on, and plants reporting a problem."""

    key = "problems"
    roles = (Role.PROBLEM, Role.PLANT)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out = []
        for entity_id in sorted(ctx.world.with_role(Role.PROBLEM)):
            s = state(ctx, entity_id)
            if s is None or s.state != "on":
                continue
            area = area_of(ctx, entity_id)
            device_id = device_of(ctx, entity_id)
            out.append(
                Signal(
                    id=f"problem:{entity_id}",
                    detector=self.key,
                    kind="problem_entity",
                    category=Category.MAINTENANCE,
                    severity=int(setting(ctx, "detectors.problems.severity", entity_id)),
                    entities=(entity_id,),
                    device_id=device_id,
                    area_id=area,
                    since=s.last_changed,
                    data={
                        "name": name(ctx, entity_id),
                        "device": ctx.world.device_name(device_id),
                        "where": where(ctx, area_id=area),
                    },
                    need=Need.MEMBER,
                    confidence=0.6,  # generic: AI triage may refine what this means
                )
            )
        for entity_id in sorted(ctx.world.with_role(Role.PLANT)):
            s = state(ctx, entity_id)
            if s is None or s.state != "problem":
                continue
            area = area_of(ctx, entity_id)
            out.append(
                Signal(
                    id=f"plant:{entity_id}",
                    detector=self.key,
                    kind="plant_problem",
                    category=Category.MAINTENANCE,
                    severity=int(setting(ctx, "detectors.problems.plant_severity", entity_id)),
                    entities=(entity_id,),
                    area_id=area,
                    since=s.last_changed,
                    data={
                        "name": name(ctx, entity_id),
                        "problem": str(s.attributes.get("problem") or ""),
                        "where": where(ctx, area_id=area),
                    },
                    need=Need.MEMBER,
                    root="plants",
                )
            )
        return out


class StaleSensorDetector(Detector):
    """Measurement sensors (temperature, humidity, CO2, power…) that stopped reporting but are not unavailable."""

    key = "stale"
    ROLES = (Role.TEMPERATURE, Role.HUMIDITY, Role.CO2, Role.PM25, Role.SOIL_MOISTURE, Role.ILLUMINANCE)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out = []
        for entity_id in sorted(ctx.world.with_role(*self.ROLES)):
            s = state(ctx, entity_id)
            info = ctx.world.entity(entity_id)
            if s is None or info is None or s.state in UNAVAILABLE or info.category:
                continue
            hours = float(setting(ctx, "detectors.stale.hours", entity_id))
            if hours <= 0:
                continue
            last = getattr(s, "last_reported", None) or s.last_updated
            if ctx.now - last < timedelta(hours=hours):
                continue
            area = area_of(ctx, entity_id)
            out.append(
                Signal(
                    id=f"stale:{entity_id}",
                    detector=self.key,
                    kind="stale_sensor",
                    category=Category.SYSTEM,
                    severity=int(setting(ctx, "detectors.stale.severity", entity_id)),
                    entities=(entity_id,),
                    device_id=info.device_id,
                    area_id=area,
                    since=last,
                    data={"name": name(ctx, entity_id), "where": where(ctx, area_id=area), "since": clock(last)},
                    need=Need.MEMBER,
                    tags=frozenset(),
                )
            )
        return out
