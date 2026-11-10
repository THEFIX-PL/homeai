"""How the home is used: lights left on in an empty home, windows open while the same room is heated."""

from __future__ import annotations

from ...world import Role
from ..base import Category, DetectionContext, Detector, Need, Signal
from .util import held_for, name, setting, state


class LightsAwayDetector(Detector):
    """Lights on while every resident is away, for at least `detectors.lights_away.minutes`."""

    key = "lights_away"
    roles = (Role.LIGHT, Role.PERSON)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        if not ctx.presence.everyone_away():
            return []
        on = []
        for entity_id in sorted(ctx.world.with_role(Role.LIGHT)):
            info = ctx.world.entity(entity_id)
            s = state(ctx, entity_id)
            if info is None or s is None or s.state != "on" or info.category:
                continue
            if not held_for(s, ctx.now, float(setting(ctx, "detectors.lights_away.minutes", entity_id))):
                continue
            if not setting(ctx, "detectors.lights_away.enabled", entity_id):
                continue
            on.append(entity_id)
        if not on:
            return []
        areas = sorted({ctx.world.area_name(ctx.world.entity(e).area_id) or name(ctx, e) for e in on})
        return [
            Signal(
                id="lights_away",
                detector=self.key,
                kind="lights_away",
                category=Category.ENERGY,
                severity=int(ctx.settings.get("detectors.lights_away.severity")),
                entities=tuple(on),
                data={"where": areas, "count": len(on)},
                need=Need.NOBODY,
                action={"service": "light.turn_off", "data": {"entity_id": on}, "label": "turn_off_lights"},
            )
        ]


class WindowHeatingDetector(Detector):
    """A window open for a while in a room whose climate device is heating."""

    key = "window_heating"
    roles = (Role.WINDOW, Role.OPENING, Role.CLIMATE)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out = []
        heating_areas: dict[str, list[str]] = {}
        for entity_id in ctx.world.with_role(Role.CLIMATE):
            info = ctx.world.entity(entity_id)
            s = state(ctx, entity_id)
            if info is None or info.area_id is None or s is None:
                continue
            if s.attributes.get("hvac_action") == "heating" or (
                s.state == "heat" and s.attributes.get("hvac_action") in (None, "heating")
            ):
                heating_areas.setdefault(info.area_id, []).append(entity_id)
        for entity_id in sorted(ctx.world.with_role(Role.WINDOW)):
            info = ctx.world.entity(entity_id)
            s = state(ctx, entity_id)
            if info is None or s is None or s.state != "on" or info.area_id not in heating_areas:
                continue
            if not held_for(s, ctx.now, float(setting(ctx, "detectors.window_heating.minutes", entity_id))):
                continue
            out.append(
                Signal(
                    id=f"window_heating:{entity_id}",
                    detector=self.key,
                    kind="window_heating",
                    category=Category.ENERGY,
                    severity=int(setting(ctx, "detectors.window_heating.severity", entity_id)),
                    entities=(entity_id, *heating_areas[info.area_id]),
                    area_id=info.area_id,
                    since=s.last_changed,
                    data={"name": name(ctx, entity_id), "where": ctx.world.area_name(info.area_id)},
                    need=Need.MEMBER,
                )
            )
        return out
