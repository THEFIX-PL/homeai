"""Presence exceptions: trips, guests, working from home, sickness — for one person or the household.

Shown as `calendar.homeai_presence`, which any integration or automation can read with a calendar trigger.
Presence uses them: a household trip (or everyone away) counts as vacation; a person's trip makes them
expected away.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, LOGGER

STORAGE_KEY = f"{DOMAIN}.presence_exceptions"
KINDS = ("away", "vacation", "guests", "home_office", "sick")
AWAY_KINDS = frozenset({"away", "vacation"})
KEYWORDS = {  # words in a calendar event title that pick the kind (English and Polish)
    "vacation": ("vacation", "holiday", "trip", "urlop", "wakacje", "wyjazd", "ferie"),
    "away": ("away", "out", "nieobecn", "poza domem", "delegacja"),
    "guests": ("guest", "visit", "goście", "gości", "wizyta"),
    "home_office": ("home office", "working from home", "wfh", "praca z domu", "zdalnie"),
    "sick": ("sick", "ill", "chory", "chora", "choroba", "l4"),
}


def parse_moment(value: Any, *, end: bool = False) -> datetime:
    """A date (whole day) or a datetime, in UTC. An end date means the end of that day."""
    if isinstance(value, datetime):
        return dt_util.as_utc(value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone()))
    if isinstance(value, date):
        day = value + timedelta(days=1) if end else value
        return dt_util.as_utc(datetime.combine(day, time(0), tzinfo=dt_util.get_default_time_zone()))
    text = str(value).strip()
    if len(text) == 10:  # YYYY-MM-DD: a whole day
        return parse_moment(date.fromisoformat(text), end=end)
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        raise ValueError("date")
    return parse_moment(parsed)


class PresenceExceptions:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass: HomeAssistant = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.items: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[], None]] = []

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.items = {i["id"]: i for i in data.get("items", []) if isinstance(i, dict) and "id" in i}
        self._prune()
        self.rt.presence.exceptions = self

    async def async_unload(self) -> None:
        self.rt.presence.exceptions = None
        await self._store.async_save({"items": list(self.items.values())})

    @callback
    def listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _changed(self) -> None:
        self._store.async_delay_save(lambda: {"items": list(self.items.values())}, 2)
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                LOGGER.exception("Presence exception listener failed")

    def _prune(self) -> None:
        keep = timedelta(days=int(self.rt.settings.get("schedule.presence_keep_days")))
        now = dt_util.utcnow()
        for item_id, item in list(self.items.items()):
            if parse_moment(item["end"]) < now - keep:
                del self.items[item_id]

    # ——— Editing ———
    def save(self, raw: dict[str, Any], item_id: str | None = None, author: str | None = None) -> dict[str, Any]:
        kind = raw.get("kind")
        if kind not in KINDS:
            raise ValueError("kind")
        person = raw.get("person") or None
        if person is not None and person not in self.rt.world.persons:
            raise ValueError("person")
        start, end = parse_moment(raw["start"]), parse_moment(raw["end"], end=True)
        if end <= start:
            raise ValueError("end_before_start")
        item = {
            "id": item_id or ulid_util.ulid_now().lower(),
            "kind": kind,
            "person": person,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "note": str(raw.get("note") or "")[:300],
            "author": author,
        }
        self.items[item["id"]] = item
        self.rt.journal.add("schedule", self.rt.text("journal|presence_saved", what=self.describe(item)))
        self._changed()
        return item

    def remove(self, item_id: str) -> bool:
        if self.items.pop(item_id, None) is None:
            return False
        self._changed()
        return True

    def from_summary(self, summary: str, description: str | None) -> dict[str, Any]:
        """Kind and person guessed from a calendar event title, e.g. “Vacation Anna”, “Goście”."""
        text = summary.lower()
        kind = next((k for k, words in KEYWORDS.items() if any(w in text for w in words)), "away")
        person = next((p.entity_id for p in self.rt.world.persons.values() if p.name and p.name.lower() in text), None)
        return {"kind": kind, "person": person, "note": description or summary}

    def describe(self, item: dict[str, Any]) -> str:
        kind = self.rt.text(f"presence|{item['kind']}")
        person = self.rt.world.persons.get(item["person"]) if item.get("person") else None
        return f"{kind}: {person.name}" if person else kind

    # ——— Queries ———
    def active(self, at: datetime | None = None) -> list[dict[str, Any]]:
        at = at or dt_util.utcnow()
        return [i for i in self.items.values() if parse_moment(i["start"]) <= at < parse_moment(i["end"])]

    def between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return sorted(
            (i for i in self.items.values() if parse_moment(i["start"]) < end and parse_moment(i["end"]) > start),
            key=lambda i: i["start"],
        )

    def household_away(self, at: datetime | None = None) -> bool:
        active = self.active(at)
        if any(i["kind"] in AWAY_KINDS and not i.get("person") for i in active):
            return True
        residents = self.rt.presence.residents()
        away = {i["person"] for i in active if i["kind"] in AWAY_KINDS and i.get("person")}
        return bool(residents) and all(p.entity_id in away for p in residents)

    def person_away(self, person_id: str, at: datetime | None = None) -> bool:
        return any(i["kind"] in AWAY_KINDS and i.get("person") in (None, person_id) for i in self.active(at))

    def guests(self, at: datetime | None = None) -> bool:
        return any(i["kind"] == "guests" for i in self.active(at))

    def diagnostics(self) -> dict[str, Any]:
        return {"items": len(self.items), "active": self.active()}
