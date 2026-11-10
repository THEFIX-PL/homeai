"""The context card: a compact, privacy-filtered description of the home for prompts.

Stable facts (rooms, people, roles) come first so they can be cached; the moment (time, presence, open
situations, recent events) comes last.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from .privacy import Privacy, clean

KEEP_ATTRIBUTES = (
    "unit_of_measurement",
    "device_class",
    "current_temperature",
    "temperature",
    "hvac_action",
    "battery_level",
    "brightness",
    "current_position",
)


def home_card(rt: Any, privacy: Privacy) -> str:
    """Rooms and people: changes rarely."""
    world = rt.world
    floors: dict[str, list[str]] = {}
    for area in sorted(world.areas.values(), key=lambda a: a.name):
        floor = world.floors.get(area.floor_id).name if area.floor_id and area.floor_id in world.floors else ""
        floors.setdefault(floor, []).append(privacy.area(area.name))
    lines = ["<home>"]
    for floor, areas in floors.items():
        lines.append(f"{privacy.area(floor) or 'Rooms'}: {', '.join(areas)}")
    people = [f"{privacy.person(p.name)} ({rt.presence.role(p.entity_id)})" for p in world.persons.values()]
    if people:
        lines.append(f"People: {', '.join(people)}")
    lines.append(f"Language for people: {rt.language}")
    lines.append("</home>")
    return "\n".join(lines)


def moment_card(rt: Any, privacy: Privacy, *, situations: int = 8, journal: int = 8) -> str:
    """Now: time, presence and sleep, house mode, open situations, recent events."""
    now = dt_util.now()
    presence = rt.presence
    lines = [f"<now>{now.strftime('%Y-%m-%d %A %H:%M')} ({presence.day_part()})</now>", "<presence>"]
    for p in presence.people():
        state = "home" if p.home else "away"
        if p.sleep.asleep:
            state += ", asleep"
        lines.append(f"{privacy.person(p.name)}: {state}")
    if (mode := presence.house_mode()) is not None:
        lines.append(f"House mode: {clean(mode, 40)}")
    if presence.vacation():
        lines.append("Household is on vacation")
    lines.append("</presence>")
    minimal = privacy.level == "minimal"  # titles and journal texts carry real names and rooms
    engine = rt.module("situations")
    if engine is not None and (open_ := engine.open()):
        lines.append("<open_situations>")
        for s in open_[:situations]:
            title = s.kind if minimal else clean(s.title(rt.language), 100)
            lines.append(f"- {title} [severity {s.severity}, {s.category}, who {s.assessment.get('who', '?')}]")
        lines.append("</open_situations>")
    recent = [] if minimal else rt.journal.recent(journal)
    if recent:
        lines.append("<recent_events>")
        lines.extend(f"- {e['ts'][11:16]} {clean(e['text'], 120)}" for e in reversed(recent))
        lines.append("</recent_events>")
    return "\n".join(lines)


def entity_lines(rt: Any, privacy: Privacy, entity_ids: list[str] | tuple[str, ...]) -> list[str]:
    out = []
    for entity_id in entity_ids:
        if not privacy.allowed(entity_id):
            continue
        state = rt.hass.states.get(entity_id)
        if state is None:
            continue
        info = rt.world.entity(entity_id)
        area = privacy.area(rt.world.area_name(info.area_id)) if info and info.area_id else ""
        attrs = privacy.attributes(dict(state.attributes), KEEP_ATTRIBUTES)
        since = dt_util.as_local(state.last_changed).strftime("%m-%d %H:%M")
        extra = f" {attrs}" if attrs else ""
        out.append(
            f"- {privacy.entity_name(entity_id)} ({entity_id.split('.', 1)[0]}{', ' + area if area else ''}): "
            f"{clean(state.state, 40)} since {since}{extra}"
        )
    return out
