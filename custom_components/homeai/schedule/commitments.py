"""Commitments: “tell me when …”. A person asks HomeAI to watch an entity; when it meets the condition, that
person is told once and the commitment ends. Commitments expire after a while so nothing is watched forever.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from .. import i18n
from ..const import DOMAIN, LOGGER

STORAGE_KEY = f"{DOMAIN}.commitments"
CONDITIONS = ("state", "not_state", "above", "below", "changes")
UNAVAILABLE = ("unavailable", "unknown")


class CommitmentError(ValueError):
    """A commitment that cannot be kept; the message is a short reason."""


def met(condition: str, value: Any, old: str | None, new: str) -> bool:
    """Whether a state change from `old` to `new` meets the condition."""
    if new in UNAVAILABLE:
        return False
    if condition == "changes":
        return old is not None and old != new
    if condition == "state":
        return new == str(value)
    if condition == "not_state":
        return new != str(value)
    try:
        number = float(new)
    except ValueError:
        return False
    return number > float(value) if condition == "above" else number < float(value)


class Commitments:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass: HomeAssistant = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.items: dict[str, dict[str, Any]] = {}
        self._unsub: Callable[[], None] | None = None
        self._unsub_tick: Callable[[], None] = lambda: None
        self._listeners: list[Callable[[], None]] = []

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.items = {i["id"]: i for i in data.get("items", []) if isinstance(i, dict) and "id" in i}
        self._expire(dt_util.utcnow())
        self._track()
        self._unsub_tick = self.rt.on_tick(self.expire)

    async def async_unload(self) -> None:
        self._unsub_tick()
        if self._unsub:
            self._unsub()
            self._unsub = None
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"items": list(self.items.values())}

    @callback
    def listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _changed(self) -> None:
        self._store.async_delay_save(self._data, 2)
        self._track()
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                LOGGER.exception("Commitment listener failed")

    def _track(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        entities = sorted({i["entity_id"] for i in self.items.values()})
        if entities:
            self._unsub = async_track_state_change_event(self.hass, entities, self._on_change)

    # ——— Editing ———
    def add(
        self,
        user_id: str | None,
        entity_id: str,
        condition: str,
        value: Any = None,
        message: str = "",
        hours: float | None = None,
    ) -> dict[str, Any]:
        settings = self.rt.settings
        person = next((p for p in self.rt.world.persons.values() if user_id and p.user_id == user_id), None)
        if person is None:
            raise CommitmentError("person_required")
        if condition not in CONDITIONS:
            raise CommitmentError("condition")
        if condition in ("above", "below"):
            try:
                value = float(value)
            except (TypeError, ValueError) as err:
                raise CommitmentError("value_number") from err
        elif condition in ("state", "not_state"):
            if value in (None, ""):
                raise CommitmentError("value_required")
            value = str(value)[:100]
        else:
            value = None
        if self.hass.states.get(entity_id) is None:
            raise CommitmentError("unknown_entity")
        mine = [i for i in self.items.values() if i["person"] == person.entity_id]
        if len(mine) >= int(settings.get("schedule.watch_max")):
            raise CommitmentError("too_many")
        limit = float(settings.get("schedule.watch_hours"))
        hours = min(float(hours), limit) if hours else limit
        now = dt_util.utcnow()
        item = {
            "id": ulid_util.ulid_now().lower(),
            "person": person.entity_id,
            "user_id": user_id,
            "entity_id": entity_id,
            "condition": condition,
            "value": value,
            "message": str(message or "").strip()[:300],
            "created": now.isoformat(timespec="seconds"),
            "expires": (now + timedelta(hours=hours)).isoformat(timespec="seconds"),
        }
        self.items[item["id"]] = item
        self.rt.journal.add("schedule", self.rt.text("journal|watch_added", what=self.describe(item)), actor="person")
        self._changed()
        return item

    def remove(self, item_id: str, user_id: str | None = None, *, admin: bool = True) -> bool:
        item = self.items.get(item_id)
        if item is None or (not admin and item.get("user_id") != user_id):
            return False
        del self.items[item_id]
        self._changed()
        return True

    def of_user(self, user_id: str | None, *, admin: bool = False) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if admin or i.get("user_id") == user_id]

    def describe(self, item: dict[str, Any]) -> str:
        what = self.rt.world.display_name(item["entity_id"]) or item["entity_id"]
        value = item.get("value")
        if isinstance(value, str) and i18n.has(self.rt.language, f"states|{value}"):
            value = self.rt.text(f"states|{value}")  # “off” → “wyłączone”
        return self.rt.text(f"schedule|watch_{item['condition']}", name=what, value=value)

    # ——— Watching ———
    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None:
            return
        old = event.data["old_state"]
        for item in [i for i in self.items.values() if i["entity_id"] == new.entity_id]:
            if met(item["condition"], item.get("value"), old.state if old else None, new.state):
                del self.items[item["id"]]
                self.hass.async_create_task(self._tell(item), eager_start=False)

    async def _tell(self, item: dict[str, Any]) -> None:
        router = self.rt.module("notify")
        from ..notify.recipients import targets_for

        text = item["message"] or self.rt.text("schedule|watch_done", what=self.describe(item))
        sent = False
        for target in targets_for(self.hass, self.rt.settings, item["person"]) if router else []:
            try:
                await router._send(
                    target, self.rt.text("schedule|watch_title"), text, {"tag": f"homeai_watch_{item['id']}"}
                )
                sent = True
            except Exception as err:
                LOGGER.debug("Commitment message to %s failed: %s", target, err)
        self.rt.journal.add(
            "schedule", self.rt.text("journal|watch_met", what=self.describe(item)), result="sent" if sent else "failed"
        )
        self._changed()

    @callback
    def expire(self, now: datetime) -> None:
        if self._expire(now):
            self._changed()

    def _expire(self, now: datetime) -> bool:
        gone = [
            i["id"]
            for i in self.items.values()
            if (end := dt_util.parse_datetime(i.get("expires") or "")) is None or end <= now
        ]
        for item_id in gone:
            del self.items[item_id]
        return bool(gone)

    def diagnostics(self) -> dict[str, Any]:
        return {"watching": len(self.items)}
