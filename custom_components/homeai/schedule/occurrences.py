"""When a plan entry happens: once, daily, on chosen weekdays, or relative to sunrise or sunset."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from ..settings import parse_time

KINDS = ("once", "daily", "weekly", "sun")
SUN_EVENTS = ("sunrise", "sunset", "dawn", "dusk", "solar_noon")


def validate_when(when: Any) -> dict[str, Any]:
    """Normalise a `when` mapping; raises ValueError with a short reason."""
    if not isinstance(when, dict) or when.get("kind") not in KINDS:
        raise ValueError("when.kind is once, daily, weekly or sun")
    kind = when["kind"]
    out: dict[str, Any] = {"kind": kind}
    if kind in ("once", "daily", "weekly"):
        out["time"] = parse_time(str(when.get("time", ""))).strftime("%H:%M")
    if kind == "once":
        try:
            out["date"] = date.fromisoformat(str(when.get("date"))).isoformat()
        except ValueError as err:
            raise ValueError("when.date is YYYY-MM-DD") from err
    if kind == "weekly":
        days = when.get("days")
        if not isinstance(days, list) or not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise ValueError("when.days: weekdays 0 (Monday) to 6")
        out["days"] = sorted(set(days))
    if kind == "sun":
        if when.get("event") not in SUN_EVENTS:
            raise ValueError("when.event is sunrise, sunset, dawn, dusk or solar_noon")
        out["event"] = when["event"]
        offset = when.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or not -720 <= offset <= 720:
            raise ValueError("when.offset is -720 to 720 minutes")
        out["offset"] = offset
        days = when.get("days")
        if days:
            if not isinstance(days, list) or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
                raise ValueError("when.days: weekdays 0 (Monday) to 6")
            out["days"] = sorted(set(days))
    return out


def _at(day: date, t: time) -> datetime:
    return dt_util.as_utc(datetime.combine(day, t, tzinfo=dt_util.get_default_time_zone()))


def on_day(hass: HomeAssistant, when: dict[str, Any], day: date) -> datetime | None:
    """The occurrence on a local date, in UTC, or None."""
    kind = when["kind"]
    if kind == "once":
        return _at(day, parse_time(when["time"])) if day.isoformat() == when["date"] else None
    if kind == "daily":
        return _at(day, parse_time(when["time"]))
    if kind == "weekly":
        return _at(day, parse_time(when["time"])) if day.weekday() in when["days"] else None
    if kind == "sun":
        if when.get("days") and day.weekday() not in when["days"]:
            return None
        event = get_astral_event_date(hass, when["event"], day)
        if event is None:
            return None
        return dt_util.as_utc(event) + timedelta(minutes=when.get("offset", 0))
    return None


def between(hass: HomeAssistant, when: dict[str, Any], start: datetime, end: datetime) -> list[datetime]:
    """Occurrences with start < t <= end (UTC)."""
    out: list[datetime] = []
    day = dt_util.as_local(start).date() - timedelta(days=1)
    last = dt_util.as_local(end).date() + timedelta(days=1)
    while day <= last:
        t = on_day(hass, when, day)
        if t is not None and start < t <= end:
            out.append(t)
        day += timedelta(days=1)
    return out


def next_after(hass: HomeAssistant, when: dict[str, Any], after: datetime, horizon_days: int = 400) -> datetime | None:
    if when["kind"] == "once":
        t = on_day(hass, when, date.fromisoformat(when["date"]))
        return t if t is not None and t > after else None
    found = between(hass, when, after, after + timedelta(days=8))
    if found:
        return found[0]
    found = between(hass, when, after, after + timedelta(days=horizon_days))
    return found[0] if found else None
