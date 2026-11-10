"""Situation engine: correlates signals into situations and runs their lifecycle.

- Signals with the same `root` form one situation; a signal that `suppresses` tags (internet down → "cloud")
  pulls the signals it explains into its own situation instead of letting each open one.
- A new situation waits `situations.min_duration` (per category) before it opens, so flickers wake nobody;
  during the startup grace period nothing opens.
- When its signals disappear it waits `situations.close_after` before resolving; if they come back it reopens.
- Processors (triage, repair, notifications, entities) are called in order for every lifecycle event.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, EVENT_SITUATION, LOGGER
from ..signals.base import Signal
from .model import Phase, Situation

STORAGE_KEY = f"{DOMAIN}.situations"
STORAGE_VERSION = 1
HISTORY_LIMIT = 300

Processor = Callable[[str, Situation], Awaitable[None] | None]


class SituationEngine:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass: HomeAssistant = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)
        self.situations: dict[str, Situation] = {}  # id → live situation (pending/open/clearing)
        self.resolved: list[Situation] = []
        self.mutes: dict[str, str] = {}  # signal id → ISO until (dismissed as “not a problem”)
        self.stats: dict[str, dict[str, int]] = {}  # kind → counters for calibration
        self.processors: list[tuple[str, Processor]] = []
        self._listeners: list[Callable[[str, Situation], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._timer: Callable[[], None] | None = None
        self._signals: dict[str, Signal] = {}
        self._lock = asyncio.Lock()

    # ——— Lifecycle ———
    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        for raw in data.get("situations") or []:
            try:
                s = Situation.from_dict(raw)
            except KeyError, ValueError:
                continue
            self.situations[s.id] = s
        self.resolved = []
        for raw in data.get("resolved") or []:
            try:
                self.resolved.append(Situation.from_dict(raw))
            except KeyError, ValueError:
                continue
        self.mutes = dict(data.get("mutes") or {})
        self.stats = dict(data.get("stats") or {})
        hub = self.rt.module("signals")
        if hub is not None:
            self._signals = dict(hub.signals)
            self._unsubs.append(hub.listen(self.on_signals))
        self._unsubs.append(self.rt.on_tick(self.process))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._timer:
            self._timer()
        await self._store.async_save(self._data())

    def add_processor(self, name: str, processor: Processor) -> None:
        self.processors.append((name, processor))

    @callback
    def listen(self, cb: Callable[[str, Situation], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _data(self) -> dict[str, Any]:
        return {
            "situations": [s.as_dict() for s in self.situations.values()],
            "resolved": [s.as_dict() for s in self.resolved[-HISTORY_LIMIT:]],
            "mutes": self.mutes,
            "stats": self.stats,
        }

    @callback
    def save(self) -> None:
        self._store.async_delay_save(self._data, 5)

    # ——— Signals in ———
    @callback
    def on_signals(self, changes: dict[str, Signal | None]) -> None:
        for sid, signal in changes.items():
            if signal is None:
                self._signals.pop(sid, None)
            else:
                self._signals[sid] = signal
        self.hass.async_create_task(self.process(dt_util.utcnow()))

    def _muted(self, signal: Signal, now: datetime) -> bool:
        until = self.mutes.get(signal.id)
        if until is None:
            return False
        if (t := dt_util.parse_datetime(until)) is None or t <= now:
            self.mutes.pop(signal.id, None)
            return False
        return True

    def _groups(self, now: datetime) -> dict[str, tuple[dict[str, Signal], dict[str, Signal]]]:
        """group → (active signals, suppressed signals)."""
        active = {sid: s for sid, s in self._signals.items() if not self._muted(s, now)}
        suppressors = [s for s in active.values() if s.suppresses]
        groups: dict[str, tuple[dict[str, Signal], dict[str, Signal]]] = {}
        for sid, s in active.items():
            explained_by = next((x for x in suppressors if x.id != sid and x.suppresses & s.tags), None)
            if explained_by is not None:
                groups.setdefault(explained_by.group, ({}, {}))[1][sid] = s
            else:
                groups.setdefault(s.group, ({}, {}))[0][sid] = s
        return {g: v for g, v in groups.items() if v[0]}

    # ——— Lifecycle processing ———
    async def process(self, now: datetime | None = None) -> None:
        async with self._lock:
            await self._process(now or dt_util.utcnow())

    async def _process(self, now: datetime) -> None:
        groups = self._groups(now)
        by_group = {s.group: s for s in self.situations.values()}
        events: list[tuple[str, Situation]] = []

        for group, (signals, suppressed) in groups.items():
            s = by_group.get(group)
            if s is None:
                s = Situation(id=ulid_util.ulid_now().lower(), group=group, first_seen=now)
                self.situations[s.id] = s
                s.log("seen")
            before = (s.severity, set(s.signals))
            s.signals, s.suppressed = signals, suppressed
            if s.phase is Phase.CLEARING:
                s.phase, s.clearing_since = Phase.OPEN, None
                s.updated_at = now
                s.log("reopened")
                events.append(("updated", s))
            elif s.phase is Phase.OPEN and before != (max(x.severity for x in signals.values()), set(signals)):
                s.updated_at = now
                events.append(("updated", s))

        for s in list(self.situations.values()):
            if s.group in groups:
                if s.phase is Phase.PENDING and self._ready_to_open(s, now):
                    s.phase, s.opened_at, s.updated_at = Phase.OPEN, now, now
                    s.log("opened")
                    self._count(s.kind, "opened")
                    events.append(("opened", s))
                continue
            # no active signals any more
            if s.phase is Phase.PENDING:
                del self.situations[s.id]
            elif s.phase is Phase.OPEN:
                s.phase, s.clearing_since = Phase.CLEARING, now
                s.log("clearing")
            elif s.phase is Phase.CLEARING and s.clearing_since and now - s.clearing_since >= self._close_after(s):
                s.phase, s.resolved_at = Phase.RESOLVED, now
                s.log("resolved")
                del self.situations[s.id]
                self.resolved.append(s)
                del self.resolved[:-HISTORY_LIMIT]
                events.append(("resolved", s))

        for event, s in events:
            await self.emit(event, s)
        if events:
            self.save()
        self._schedule_next(now)

    def _ready_to_open(self, s: Situation, now: datetime) -> bool:
        if not self.rt.ready:
            return False
        p = s.primary
        key = f"situations.min_duration_{p.category}" if p else "situations.min_duration"
        seconds = self.rt.settings.get(key) if key in self.rt.settings.registry else None
        if seconds is None:
            seconds = self.rt.settings.get("situations.min_duration")
        return now - s.first_seen >= timedelta(seconds=int(seconds))

    def _close_after(self, s: Situation) -> timedelta:
        return timedelta(seconds=int(self.rt.settings.get("situations.close_after")))

    def _schedule_next(self, now: datetime) -> None:
        """Wake up exactly when the next pending/clearing situation is due (ticks are coarser)."""
        due: list[datetime] = []
        for s in self.situations.values():
            if s.phase is Phase.PENDING and self.rt.ready:
                p = s.primary
                key = f"situations.min_duration_{p.category}" if p else "situations.min_duration"
                seconds = self.rt.settings.get(key) if key in self.rt.settings.registry else None
                seconds = seconds if seconds is not None else self.rt.settings.get("situations.min_duration")
                due.append(s.first_seen + timedelta(seconds=int(seconds)))
            elif s.phase is Phase.CLEARING and s.clearing_since:
                due.append(s.clearing_since + self._close_after(s))
        if self._timer:
            self._timer()
            self._timer = None
        if not due:
            return
        delay = max(0.5, (min(due) - now).total_seconds() + 0.5)

        @callback
        def wake(_now: datetime) -> None:
            self._timer = None
            self.hass.async_create_task(self.process())

        self._timer = async_call_later(self.hass, delay, wake)

    async def emit(self, event: str, s: Situation) -> None:
        """Run processors in order, then tell listeners and the bus."""
        for name, processor in self.processors:
            try:
                result = processor(event, s)
                if result is not None:
                    await result
            except Exception:
                LOGGER.exception("Situation processor %s failed on %s", name, event)
        for cb in list(self._listeners):
            try:
                cb(event, s)
            except Exception:
                LOGGER.exception("Situation listener failed")
        self.hass.bus.async_fire(
            EVENT_SITUATION,
            {
                "event": event,
                "id": s.id,
                "kind": s.kind,
                "category": s.category,
                "severity": s.severity,
                "title": s.title(self.rt.language),
                "who": s.assessment.get("who"),
                "entities": s.entities,
            },
        )

    # ——— People's reactions ———
    def get(self, situation_id: str) -> Situation | None:
        return self.situations.get(situation_id)

    async def acknowledge(self, situation_id: str, who: str) -> Situation | None:
        s = self.situations.get(situation_id)
        if s is None:
            return None
        s.acked_by, s.acked_at = who, dt_util.utcnow()
        s.log("acknowledged", who=who)
        self._count(s.kind, "acknowledged")
        await self.emit("acknowledged", s)
        self.save()
        return s

    async def handle(self, situation_id: str, who: str) -> Situation | None:
        """“I'll take care of it”: acknowledged and assigned."""
        s = self.situations.get(situation_id)
        if s is None:
            return None
        s.handled_by = who
        s.acked_by, s.acked_at = who, dt_util.utcnow()
        s.log("handled", who=who)
        await self.emit("handled", s)
        self.save()
        return s

    async def snooze(self, situation_id: str, minutes: int, who: str) -> Situation | None:
        s = self.situations.get(situation_id)
        if s is None:
            return None
        s.snoozed_until = dt_util.utcnow() + timedelta(minutes=minutes)
        s.log("snoozed", who=who, minutes=minutes)
        await self.emit("snoozed", s)
        self.save()
        return s

    async def escalate(self, s: Situation, reason: str) -> None:
        """A repair failed or needs a person: run the pipeline again so triage and notifications react."""
        s.log("escalated", reason=reason)
        s.updated_at = dt_util.utcnow()
        await self.emit("escalated", s)
        self.save()

    async def reassessed(self, s: Situation) -> None:
        """An AI tier changed the assessment: notifications and entities follow it."""
        s.updated_at = dt_util.utcnow()
        await self.emit("updated", s)
        self.save()

    async def dismiss(self, situation_id: str, who: str) -> Situation | None:
        """“Not a problem”: mutes its signals for `situations.dismiss_days` and teaches calibration."""
        s = self.situations.get(situation_id)
        if s is None:
            return None
        days = int(self.rt.settings.get("situations.dismiss_days"))
        until = (dt_util.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
        for sid in s.signals:
            self.mutes[sid] = until
        self._count(s.kind, "dismissed")
        s.log("dismissed", who=who)
        await self.emit("dismissed", s)
        s.phase, s.resolved_at = Phase.RESOLVED, dt_util.utcnow()
        self.situations.pop(s.id, None)
        self.resolved.append(s)
        await self.emit("resolved", s)
        self.save()
        return s

    def _count(self, kind: str, what: str) -> None:
        counters = self.stats.setdefault(kind, {})
        counters[what] = counters.get(what, 0) + 1

    # ——— Views ———
    def open(self) -> list[Situation]:
        return sorted(
            (s for s in self.situations.values() if s.active),
            key=lambda s: (-s.severity, s.opened_at or s.first_seen),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "live": [s.as_dict() for s in self.situations.values()],
            "resolved_recent": [s.as_dict() for s in self.resolved[-20:]],
            "mutes": self.mutes,
            "stats": self.stats,
        }
