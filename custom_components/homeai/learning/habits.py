"""Habits: the same thing done by hand at about the same time on most days becomes a proposal.

HomeAI looks at the last weeks of state changes of lights, switches, covers and climate devices. When a device is
turned on (or off, opened, closed) within a short window on enough days of the same kind (working days or
weekends), it proposes a plan entry. Nothing is saved until a person approves it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..world import Role

ROLES = (Role.LIGHT, Role.OUTLET, Role.SWITCH, Role.COVER, Role.CLIMATE)
SERVICE = {
    ("light", "on"): "light.turn_on",
    ("light", "off"): "light.turn_off",
    ("switch", "on"): "switch.turn_on",
    ("switch", "off"): "switch.turn_off",
    ("cover", "open"): "cover.open_cover",
    ("cover", "closed"): "cover.close_cover",
    ("climate", "off"): "climate.turn_off",
    ("climate", "heat"): "climate.turn_on",
}


def find_habits(
    changes: dict[str, list[tuple[Any, str]]], *, days: int, min_days: int, window: int
) -> list[dict[str, Any]]:
    """changes: entity → [(local datetime, new state)]. Returns habit candidates."""
    found = []
    for entity_id, items in changes.items():
        domain = entity_id.split(".", 1)[0]
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for when, new in items:
            if (domain, new) not in SERVICE:
                continue
            kind = "weekend" if when.weekday() >= 5 else "workday"
            groups[(kind, new)].append(when)
        for (kind, new), times in groups.items():
            possible = sum(
                1 for d in range(days) if ((dt_util.now() - timedelta(days=d)).weekday() >= 5) == (kind == "weekend")
            )
            if possible == 0:
                continue
            minutes = sorted(t.hour * 60 + t.minute for t in times)
            best: tuple[int, int] | None = None  # (count of distinct days, centre minute)
            for centre in minutes:
                inside = {t.date() for t in times if abs((t.hour * 60 + t.minute) - centre) <= window}
                if best is None or len(inside) > best[0]:
                    best = (len(inside), centre)
            if best is None or best[0] < min_days or best[0] / possible < 0.6:
                continue
            near = [m for m in minutes if abs(m - best[1]) <= window]
            centre = round(sum(near) / len(near))
            found.append(
                {
                    "entity_id": entity_id,
                    "service": SERVICE[(domain, new)],
                    "kind": kind,
                    "time": f"{centre // 60:02d}:{centre % 60:02d}",
                    "days_seen": best[0],
                    "days_possible": possible,
                }
            )
    return found


async def collect(rt: Any, days: int) -> dict[str, list[tuple[Any, str]]]:
    hass = rt.hass
    if "recorder" not in hass.config.components:
        return {}
    from homeassistant.components.recorder import get_instance, history

    entities = sorted(e for e in rt.world.with_role(*ROLES) if not rt.world.has_label(e, "label_ignore"))[:200]
    start = dt_util.utcnow() - timedelta(days=days)

    def load() -> dict[str, list[tuple[Any, str]]]:
        out: dict[str, list[tuple[Any, str]]] = {}
        for entity_id in entities:
            states = history.state_changes_during_period(hass, start, None, entity_id, True, False, 2000, False)
            out[entity_id] = [(dt_util.as_local(s.last_changed), s.state) for s in states.get(entity_id, [])]
        return out

    return await get_instance(hass).async_add_executor_job(load)
