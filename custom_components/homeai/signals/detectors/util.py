"""Helpers shared by detectors."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import State
from homeassistant.util import dt as dt_util

from ..base import DetectionContext

UNAVAILABLE = frozenset({"unavailable", "unknown"})


def state(ctx: DetectionContext, entity_id: str) -> State | None:
    return ctx.hass.states.get(entity_id)


def is_on(ctx: DetectionContext, entity_id: str) -> bool:
    s = ctx.hass.states.get(entity_id)
    return s is not None and s.state == "on"


def held_for(s: State | None, now: datetime, minutes: float) -> bool:
    """The current state has lasted at least `minutes`."""
    return s is not None and now - s.last_changed >= timedelta(minutes=minutes)


def where(ctx: DetectionContext, entity_id: str | None = None, area_id: str | None = None) -> str:
    """Area name of an entity (or the given area); empty when unknown."""
    if area_id is None and entity_id:
        info = ctx.world.entity(entity_id)
        area_id = info.area_id if info else None
    return ctx.world.area_name(area_id)


def area_of(ctx: DetectionContext, entity_id: str) -> str | None:
    info = ctx.world.entity(entity_id)
    return info.area_id if info else None


def device_of(ctx: DetectionContext, entity_id: str) -> str | None:
    info = ctx.world.entity(entity_id)
    return info.device_id if info else None


def name(ctx: DetectionContext, entity_id: str) -> str:
    return ctx.world.display_name(entity_id)


def clock(ts: datetime | None) -> str:
    """Local time for texts: “14:05” today, “3.11 14:05” earlier."""
    if ts is None:
        return ""
    local = dt_util.as_local(ts)
    today = dt_util.now().date()
    return local.strftime("%H:%M") if local.date() == today else f"{local.day}.{local.month:02d} {local:%H:%M}"


def setting(ctx: DetectionContext, key: str, entity_id: str | None = None) -> object:
    return ctx.settings.get(key, ctx.world.target(entity_id) if entity_id else None)


def excluded_personal(ctx: DetectionContext, entity_id: str) -> bool:
    info = ctx.world.entity(entity_id)
    if info is None:
        return False
    label = ctx.world.label("label_personal")
    return label in info.labels


def critical(ctx: DetectionContext, entity_id: str) -> bool:
    info = ctx.world.entity(entity_id)
    return bool(info and ctx.world.label("label_critical") in info.labels)
