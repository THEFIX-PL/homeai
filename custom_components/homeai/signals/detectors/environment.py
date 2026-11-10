"""Indoor environment: thresholds for temperature, humidity, CO2 and PM2.5, and room sensors that disagree."""

from __future__ import annotations

from datetime import datetime, timedelta

from ...world import Role
from ..base import Category, DetectionContext, Detector, Need, Signal
from .util import area_of, device_of, name, setting, where

# (role, kind, settings key, direction, category)
CHECKS: tuple[tuple[Role, str, str, str, Category], ...] = (
    (Role.TEMPERATURE, "temperature_low", "detectors.environment.temperature_min", "below", Category.DAMAGE),
    (Role.TEMPERATURE, "temperature_high", "detectors.environment.temperature_max", "above", Category.COMFORT),
    (Role.HUMIDITY, "humidity_high", "detectors.environment.humidity_max", "above", Category.DAMAGE),
    (Role.HUMIDITY, "humidity_low", "detectors.environment.humidity_min", "below", Category.COMFORT),
    (Role.CO2, "co2_high", "detectors.environment.co2_max", "above", Category.COMFORT),
    (Role.PM25, "pm25_high", "detectors.environment.pm25_max", "above", Category.COMFORT),
)


class EnvironmentDetector(Detector):
    """Indoor values beyond their limits for at least `detectors.environment.minutes`. Outdoor sensors (no area),
    diagnostic sensors and sensors on devices that control something (a thermostat's own reading) are left out."""

    key = "environment"
    roles = (Role.TEMPERATURE, Role.HUMIDITY, Role.CO2, Role.PM25)

    def __init__(self) -> None:
        self._beyond_since: dict[tuple[str, str], datetime] = {}

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out = []
        seen: set[tuple[str, str]] = set()
        for role, kind, key, direction, category in CHECKS:
            for entity_id in sorted(ctx.world.with_role(role)):
                info = ctx.world.entity(entity_id)
                if info is None or info.area_id is None or info.category:
                    continue
                if not setting(ctx, f"{key}_enabled", entity_id):
                    continue
                if info.device_id and any(
                    (e := ctx.world.entity(x)) is not None and Role.CONTROLLABLE in e.roles
                    for x in ctx.world.of_device(info.device_id)
                ):
                    continue
                value = ctx.world.value(entity_id)
                limit = float(setting(ctx, key, entity_id))
                if value is None or not (value < limit if direction == "below" else value > limit):
                    continue
                marker = (kind, entity_id)
                seen.add(marker)
                since = self._beyond_since.setdefault(marker, ctx.now)
                if ctx.now - since < timedelta(minutes=float(setting(ctx, "detectors.environment.minutes", entity_id))):
                    continue
                area = area_of(ctx, entity_id)
                out.append(
                    Signal(
                        id=f"{kind}:{entity_id}",
                        detector=self.key,
                        kind=kind,
                        category=category,
                        severity=int(setting(ctx, f"{key}_severity", entity_id)),
                        entities=(entity_id,),
                        device_id=device_of(ctx, entity_id),
                        area_id=area,
                        since=since,
                        data={
                            "name": name(ctx, entity_id),
                            "where": where(ctx, area_id=area),
                            "value": round(value, 1),
                            "unit": info.unit or "",
                            "limit": limit,
                        },
                        need=Need.MEMBER,
                        root=f"{kind}:{area}",
                    )
                )
        for marker in [m for m in self._beyond_since if m not in seen]:
            del self._beyond_since[marker]
        return out


class DivergenceDetector(Detector):
    """Two temperature sensors in the same room that differ by more than the configured amount."""

    key = "divergence"
    roles = (Role.TEMPERATURE,)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        by_area: dict[str, list[tuple[str, float]]] = {}
        for entity_id in ctx.world.with_role(Role.TEMPERATURE):
            info = ctx.world.entity(entity_id)
            value = ctx.world.value(entity_id)
            if info is None or info.area_id is None or value is None or info.category:
                continue
            by_area.setdefault(info.area_id, []).append((entity_id, value))
        out = []
        for area_id, readings in sorted(by_area.items()):
            if len(readings) < 2:
                continue
            low = min(readings, key=lambda r: r[1])
            high = max(readings, key=lambda r: r[1])
            limit = float(ctx.settings.get("detectors.divergence.degrees", ctx.world.target(high[0])))
            if high[1] - low[1] <= limit:
                continue
            out.append(
                Signal(
                    id=f"divergence:{area_id}",
                    detector=self.key,
                    kind="sensor_divergence",
                    category=Category.SYSTEM,
                    severity=int(ctx.settings.get("detectors.divergence.severity")),
                    entities=(low[0], high[0]),
                    area_id=area_id,
                    data={
                        "where": ctx.world.area_name(area_id),
                        "diff": round(high[1] - low[1], 1),
                        "low": name(ctx, low[0]),
                        "high": name(ctx, high[0]),
                    },
                    need=Need.MEMBER,
                )
            )
        return out
