"""Calendars: the home's plan (`calendar.homeai_plan`) and presence exceptions (`calendar.homeai_presence`).

Both are a contract other integrations and automations can read with a calendar trigger. The plan calendar
lets people skip an occurrence or delete a one-off entry and add reminders; the presence calendar is fully
editable (add a trip, guests, working from home).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .entity import HomeAIEntity
from .schedule.presence import parse_moment


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    rt = entry.runtime_data
    entities: list[CalendarEntity] = []
    if rt.module("scheduler") is not None:
        entities.append(PlanCalendar(rt))
    if rt.module("presence_exceptions") is not None:
        entities.append(PresenceCalendar(rt))
    async_add_entities(entities)


class _Calendar(HomeAIEntity, CalendarEntity):
    platform_domain = "calendar"
    module_name = ""

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.rt.module(self.module_name).listen(self._changed))
        self.async_on_remove(self.rt.on_tick(lambda _now: self.async_write_ha_state()))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        events = self._events(now - timedelta(days=1), now + timedelta(days=30))
        current = [e for e in events if e.start_datetime_local <= dt_util.as_local(now) < e.end_datetime_local]
        upcoming = [e for e in events if e.start_datetime_local > dt_util.as_local(now)]
        return (current or upcoming or [None])[0]

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return self._events(dt_util.as_utc(start_date), dt_util.as_utc(end_date))


class PlanCalendar(_Calendar):
    module_name = "scheduler"
    _attr_supported_features = CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "plan")

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        minutes = int(self.rt.settings.get("schedule.event_minutes"))
        out = []
        for t, entry in self.rt.module("scheduler").all_occurrences(start, end):
            local = dt_util.as_local(t)
            if entry.get("external"):
                ends = dt_util.parse_datetime(entry["end"]) if entry.get("end") else None
                out.append(
                    CalendarEvent(
                        start=local,
                        end=dt_util.as_local(ends) if ends and ends > t else local + timedelta(minutes=minutes),
                        summary=entry["title"],
                        description=entry["source"],
                        uid=entry["id"],
                    )
                )
                continue
            out.append(
                CalendarEvent(
                    start=local,
                    end=local + timedelta(minutes=minutes),
                    summary=entry["title"],
                    description=entry.get("reminder") or entry.get("action", {}).get("service"),
                    uid=entry["id"],
                    recurrence_id=local.date().isoformat() if entry["when"]["kind"] != "once" else None,
                )
            )
        return out

    async def async_create_event(self, **kwargs: Any) -> None:
        """A new event in the plan calendar is a reminder at its start time."""
        start = kwargs.get("dtstart")
        if not isinstance(start, datetime):
            raise HomeAssistantError("A reminder needs a start time")
        local = dt_util.as_local(start if start.tzinfo else start.replace(tzinfo=dt_util.get_default_time_zone()))
        user_id = self._context.user_id if self._context else None
        await self.rt.module("scheduler").save(
            {
                "title": kwargs.get("summary") or "",
                "reminder": kwargs.get("description") or kwargs.get("summary") or "",
                "when": {"kind": "once", "date": local.date().isoformat(), "time": local.strftime("%H:%M")},
            },
            user_id,
        )

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        scheduler = self.rt.module("scheduler")
        entry = scheduler.entries.get(uid)
        if entry is None:
            raise HomeAssistantError("Unknown plan entry")
        if recurrence_id and entry["when"]["kind"] != "once" and recurrence_range != "THISANDFUTURE":
            scheduler.skip(uid, date.fromisoformat(recurrence_id[:10]))
            return
        await scheduler.remove(uid, self._context.user_id if self._context else None)


class PresenceCalendar(_Calendar):
    module_name = "presence_exceptions"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT | CalendarEntityFeature.DELETE_EVENT | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, "presence")

    def _events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        module = self.rt.module("presence_exceptions")
        out = []
        for item in module.between(start, end):
            s, e = parse_moment(item["start"]), parse_moment(item["end"])
            whole_day = dt_util.as_local(s).time() == dt_util.as_local(e).time() == datetime.min.time()
            out.append(
                CalendarEvent(
                    start=dt_util.as_local(s).date() if whole_day else dt_util.as_local(s),
                    end=dt_util.as_local(e).date() if whole_day else dt_util.as_local(e),
                    summary=module.describe(item),
                    description=item.get("note") or None,
                    uid=item["id"],
                )
            )
        return out

    def _raw(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        module = self.rt.module("presence_exceptions")
        raw = module.from_summary(str(kwargs.get("summary") or ""), kwargs.get("description"))
        start, end = kwargs.get("dtstart"), kwargs.get("dtend")
        if isinstance(start, date) and not isinstance(start, datetime) and isinstance(end, date):
            end = end - timedelta(days=1)  # calendar end dates are exclusive
        raw.update(start=start, end=end)
        return raw

    async def async_create_event(self, **kwargs: Any) -> None:
        try:
            self.rt.module("presence_exceptions").save(self._raw(kwargs))
        except (ValueError, KeyError) as err:
            raise HomeAssistantError(f"Invalid presence exception: {err}") from err

    async def async_update_event(
        self, uid: str, event: dict[str, Any], recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        module = self.rt.module("presence_exceptions")
        if uid not in module.items:
            raise HomeAssistantError("Unknown presence exception")
        try:
            module.save(self._raw(event), item_id=uid)
        except (ValueError, KeyError) as err:
            raise HomeAssistantError(f"Invalid presence exception: {err}") from err

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        if not self.rt.module("presence_exceptions").remove(uid):
            raise HomeAssistantError("Unknown presence exception")
