"""The home's plan: actions and reminders at set times, run through the executor as HomeAI.

Each entry remembers its author and the risk class approved when it was created; it never runs anything
above that class without a new approval. People who are not administrators may plan only simple device
actions (up to R2, common services); raw services are for administrators. Missed occurrences (Home Assistant
was down) run if they are at most `schedule.catch_up_minutes` late.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, LOGGER
from ..policy import ActionRequest, Risk
from .occurrences import between, next_after, validate_when

STORAGE_KEY = f"{DOMAIN}.plan"
SIMPLE_SERVICES = frozenset(
    {
        "turn_on",
        "turn_off",
        "toggle",
        "open_cover",
        "close_cover",
        "set_cover_position",
        "stop_cover",
        "set_temperature",
        "set_hvac_mode",
        "set_preset_mode",
        "set_fan_mode",
        "set_percentage",
        "start",
        "return_to_base",
        "pause",
        "media_play",
        "media_pause",
        "media_stop",
        "volume_set",
        "select_option",
        "set_value",
        "press",
        "open_valve",
        "close_valve",
        "set_humidity",
    }
)
MAX_ENTRIES = 500
EXTERNAL_ATTRIBUTE = "homeai_plan"
MAX_EXTERNAL = 50  # per entity


class PlanError(ValueError):
    """A plan entry is not valid or not allowed; the message is a short code."""


class Scheduler:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass: HomeAssistant = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.entries: dict[str, dict[str, Any]] = {}
        self._timer: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._last_fire: datetime = dt_util.utcnow()

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.entries = {e["id"]: e for e in data.get("entries", []) if isinstance(e, dict) and "id" in e}
        await self._catch_up(dt_util.utcnow())
        self._schedule()

    async def async_unload(self) -> None:
        if self._timer:
            self._timer()
            self._timer = None
        await self._store.async_save({"entries": list(self.entries.values())})

    @callback
    def listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _changed(self) -> None:
        self._store.async_delay_save(lambda: {"entries": list(self.entries.values())}, 2)
        self._schedule()
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                LOGGER.exception("Plan listener failed")

    # ——— Editing ———
    async def save(self, raw: dict[str, Any], user_id: str | None, entry_id: str | None = None) -> dict[str, Any]:
        """Create or update an entry on behalf of a person (None: an automation or HomeAI itself)."""
        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        admin = user is None or user.is_admin
        existing = self.entries.get(entry_id) if entry_id else None
        if entry_id and existing is None:
            raise PlanError("not_found")
        if existing and not admin and existing.get("author") != user_id:
            raise PlanError("not_author")
        if not admin:
            self._may_add(user_id)
        if existing is None and len(self.entries) >= min(
            MAX_ENTRIES, int(self.rt.settings.get("schedule.max_entries"))
        ):
            raise PlanError("too_many")
        title = str(raw.get("title") or "").strip()[:200]
        try:
            when = validate_when(raw.get("when"))
        except ValueError as err:
            raise PlanError(f"bad_when:{err}") from err
        entry: dict[str, Any] = {
            "id": entry_id or ulid_util.ulid_now().lower(),
            "title": title,
            "when": when,
            "enabled": bool(raw.get("enabled", True)),
            "skip_when_away": bool(raw.get("skip_when_away", self.rt.settings.get("schedule.default_skip_when_away"))),
            "skip_dates": sorted({d for d in raw.get("skip_dates", []) if isinstance(d, str)})[-100:],
            "author": existing["author"] if existing else user_id,
            "author_name": existing["author_name"] if existing else (user.name if user else "HomeAI"),
            "created": existing["created"] if existing else dt_util.utcnow().isoformat(timespec="seconds"),
            "last_run": existing.get("last_run") if existing else None,
            "last_result": existing.get("last_result") if existing else None,
        }
        if raw.get("reminder"):
            entry["reminder"] = str(raw["reminder"]).strip()[:500]
            entry["to"] = raw.get("to") if raw.get("to") in ("all", "home", "home_or_all", "admins") else "home_or_all"
            entry["approved_risk"] = int(Risk.R1)
            if not title:
                entry["title"] = entry["reminder"][:80]
        else:
            action = raw.get("action")
            if not isinstance(action, dict):
                raise PlanError("no_action")
            service = str(action.get("service") or "")
            domain, _, name = service.partition(".")
            if not domain or not name or not self.hass.services.has_service(domain, name):
                raise PlanError("unknown_service")
            entity_ids = [e for e in action.get("entity_ids") or [] if isinstance(e, str)]
            data = action.get("data") if isinstance(action.get("data"), dict) else {}
            request = ActionRequest(domain, name, dict(data), entity_ids=entity_ids)
            request.entity_ids = self.rt.module("executor").targets(request)
            risk = self.rt.module("policy").risk(request)
            if risk >= Risk.R6:
                raise PlanError("never_scheduled")
            if not admin and (risk > Risk.R2 or name not in SIMPLE_SERVICES):
                raise PlanError("admin_required")
            entry["action"] = {"service": service, "entity_ids": request.entity_ids, "data": data}
            entry["approved_risk"] = int(risk)
            if not title:
                entry["title"] = self.rt.module("executor").describe(request)
        self.entries[entry["id"]] = entry
        self.rt.journal.add(
            "schedule",
            self.rt.text("journal|plan_saved", title=entry["title"]),
            actor="person" if user_id else "homeai",
        )
        self._changed()
        return entry

    def _may_add(self, user_id: str | None) -> None:
        """`schedule.who_may_add`: everyone, residents (administrators and members, not guests) or administrators."""
        who = str(self.rt.settings.get("schedule.who_may_add"))
        if who == "everyone":
            return
        if who == "admins":
            raise PlanError("admin_required")
        person = next((p for p in self.rt.world.persons.values() if user_id and p.user_id == user_id), None)
        if person is None or self.rt.presence.role(person.entity_id) not in ("admin", "member"):
            raise PlanError("not_allowed")

    async def remove(self, entry_id: str, user_id: str | None) -> bool:
        entry = self.entries.get(entry_id)
        if entry is None:
            return False
        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        if user is not None and not user.is_admin and entry.get("author") != user_id:
            raise PlanError("not_author")
        del self.entries[entry_id]
        self.rt.journal.add("schedule", self.rt.text("journal|plan_removed", title=entry["title"]))
        self._changed()
        return True

    def skip(self, entry_id: str, day: date) -> bool:
        entry = self.entries.get(entry_id)
        if entry is None:
            return False
        if entry["when"]["kind"] == "once":
            entry["enabled"] = False
        else:
            entry["skip_dates"] = sorted({*entry.get("skip_dates", []), day.isoformat()})[-100:]
        self._changed()
        return True

    # ——— Time ———
    def occurrences(self, start: datetime, end: datetime) -> list[tuple[datetime, dict[str, Any]]]:
        out = []
        for entry in self.entries.values():
            if not entry.get("enabled"):
                continue
            for t in between(self.hass, entry["when"], start, end):
                if dt_util.as_local(t).date().isoformat() not in entry.get("skip_dates", []):
                    out.append((t, entry))
        return sorted(out, key=lambda x: x[0])

    def external(self, start: datetime, end: datetime) -> list[tuple[datetime, dict[str, Any]]]:
        """Plans other integrations publish in a `homeai_plan` attribute: a list of {start, title, end?}.
        Shown with the plan (calendar, panel, next change) but never run by HomeAI; their owner runs them."""
        if not self.rt.settings.get("schedule.external_plans"):
            return []
        out = []
        for state in self.hass.states.async_all():
            items = state.attributes.get(EXTERNAL_ATTRIBUTE)
            if not isinstance(items, list):
                continue
            for i, item in enumerate(items[:MAX_EXTERNAL]):
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                at = dt_util.parse_datetime(str(item.get("start") or item.get("at") or ""))
                if at is None:
                    continue
                at = dt_util.as_utc(at if at.tzinfo else at.replace(tzinfo=dt_util.get_default_time_zone()))
                if not start <= at < end:
                    continue
                ends = dt_util.parse_datetime(str(item.get("end") or ""))
                out.append(
                    (
                        at,
                        {
                            "id": f"external:{state.entity_id}:{i}",
                            "title": str(item["title"])[:200],
                            "source": state.entity_id,
                            "end": dt_util.as_utc(ends).isoformat() if ends else None,
                            "external": True,
                        },
                    )
                )
        return sorted(out, key=lambda x: x[0])

    def all_occurrences(self, start: datetime, end: datetime) -> list[tuple[datetime, dict[str, Any]]]:
        """HomeAI's own entries and what other integrations plan, for showing (not for running)."""
        return sorted([*self.occurrences(start, end), *self.external(start, end)], key=lambda x: x[0])

    def next_due(self, after: datetime) -> datetime | None:
        times = [
            t for e in self.entries.values() if e.get("enabled") and (t := next_after(self.hass, e["when"], after))
        ]
        return min(times) if times else None

    def _schedule(self) -> None:
        if self._timer:
            self._timer()
            self._timer = None
        due = self.next_due(dt_util.utcnow())
        if due is None:
            return

        @callback
        def fire(now: datetime) -> None:
            self._timer = None
            self.hass.async_create_task(self._fire(now), eager_start=False)

        self._timer = async_track_point_in_utc_time(self.hass, fire, due)

    async def _fire(self, now: datetime) -> None:
        start, self._last_fire = self._last_fire, now
        for t, entry in self.occurrences(start, now):
            if entry.get("last_run") and (last := dt_util.parse_datetime(entry["last_run"])) and last >= t:
                continue
            await self.run(entry, t)
        self._schedule()

    async def _catch_up(self, now: datetime) -> None:
        window = timedelta(minutes=int(self.rt.settings.get("schedule.catch_up_minutes")))
        for t, entry in self.occurrences(now - window, now):
            last = dt_util.parse_datetime(entry["last_run"]) if entry.get("last_run") else None
            if last is None or last < t:
                await self.run(entry, t)

    async def run(self, entry: dict[str, Any], at: datetime | None = None) -> str:
        at = at or dt_util.utcnow()
        entry["last_run"] = at.isoformat(timespec="seconds")
        if entry.get("skip_when_away") and (self.rt.presence.everyone_away() or self.rt.presence.vacation()):
            entry["last_result"] = "skipped_away"
            self.rt.journal.add(
                "schedule", self.rt.text("journal|plan_skipped", title=entry["title"]), result="skipped"
            )
            self._changed()
            return "skipped_away"
        if entry.get("reminder"):
            sent = await self._remind(entry)
            entry["last_result"] = "reminded" if sent else "no_recipients"
        else:
            action = entry["action"]
            domain, _, service = action["service"].partition(".")
            result = await self.rt.module("executor").execute(
                ActionRequest(
                    domain,
                    service,
                    dict(action.get("data") or {}),
                    entity_ids=list(action.get("entity_ids") or []),
                    actor="schedule",
                    approved_risk=entry.get("approved_risk"),
                    reason=entry["title"],
                    user_id=None,
                )
            )
            entry["last_result"] = result.status
        if entry["when"]["kind"] == "once":
            entry["enabled"] = False
        self._changed()
        return entry["last_result"]

    async def _remind(self, entry: dict[str, Any]) -> bool:
        router = self.rt.module("notify")
        if router is None:
            return False
        from ..notify.recipients import targets_for

        sent = False
        title = self.rt.text("notify|reminder_title")
        for person in router.recipients(entry.get("to", "home_or_all"), dt_util.utcnow()):
            if person.sleep.asleep:
                continue
            for target in targets_for(self.hass, self.rt.settings, person.entity_id):
                try:
                    await router._send(target, title, entry["reminder"], {"tag": f"homeai_plan_{entry['id']}"})
                    sent = True
                except Exception as err:
                    LOGGER.debug("Reminder to %s failed: %s", target, err)
        if sent:
            self.rt.journal.add("schedule", self.rt.text("journal|reminded", title=entry["title"]))
        return sent

    def diagnostics(self) -> dict[str, Any]:
        return {
            "entries": len(self.entries),
            "next_due": (n.isoformat() if (n := self.next_due(dt_util.utcnow())) else None),
        }
