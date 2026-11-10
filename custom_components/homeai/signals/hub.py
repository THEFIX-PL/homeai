"""Signal hub: runs detectors on relevant state changes and periodically, and reports what changed.

Each detector declares the roles it watches. A state change of a watched entity schedules that detector for a
quick re-run (debounced); every tick re-runs all of them, which also covers time-based conditions. Consumers
(the situation engine) receive only the difference: new, changed and gone signals.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import LOGGER
from .base import DetectionContext, Detector, Signal
from .detectors.behaviour import LightsAwayDetector, WindowHeatingDetector
from .detectors.environment import DivergenceDetector, EnvironmentDetector
from .detectors.external import ExternalDetector
from .detectors.maintenance import BatteryDetector, ConsumableDetector, ProblemDetector, StaleSensorDetector
from .detectors.safety import SafetyDetector, SecurityDetector
from .detectors.system import (
    AvailabilityDetector,
    BackupDetector,
    IntegrationsDetector,
    InternetDetector,
    LogDetector,
    UpdatesDetector,
)
from .system import SystemSnapshot, async_refresh

QUICK_DELAY = 1.0

Listener = Callable[[dict[str, Signal | None]], None]


def default_detectors() -> list[Detector]:
    return [
        SafetyDetector(),
        SecurityDetector(),
        InternetDetector(),
        AvailabilityDetector(),
        IntegrationsDetector(),
        BackupDetector(),
        UpdatesDetector(),
        LogDetector(),
        BatteryDetector(),
        ConsumableDetector(),
        ProblemDetector(),
        StaleSensorDetector(),
        EnvironmentDetector(),
        DivergenceDetector(),
        LightsAwayDetector(),
        WindowHeatingDetector(),
        ExternalDetector(),
    ]


class SignalHub:
    """Current signals of every detector."""

    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self.detectors: list[Detector] = default_detectors()
        self.external: ExternalDetector = next(d for d in self.detectors if isinstance(d, ExternalDetector))
        self.signals: dict[str, Signal] = {}
        self._by_detector: dict[str, set[str]] = {}
        self._watch: dict[str, set[str]] = {}  # entity_id → detector keys
        self._pending: set[str] = set()
        self._cancel_quick: Callable[[], None] | None = None
        self._listeners: list[Listener] = []
        self._unsubs: list[Callable[[], None]] = []
        self.system = SystemSnapshot()
        self._system_due: datetime | None = None

    def add_detector(self, detector: Detector) -> None:
        """Adapters add their detectors here before `async_setup`."""
        self.detectors.append(detector)

    async def async_setup(self) -> None:
        self._rebuild_watch()
        self._unsubs += [
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_state),
            self.rt.world.listen(lambda kind, _ids: self._rebuild_watch() if kind != "person" else None),
            self.rt.settings.listen("detectors", lambda _key: self.schedule_all()),
            self.rt.on_tick(self._tick),
        ]

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._cancel_quick:
            self._cancel_quick()

    @callback
    def listen(self, cb: Listener) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def context(self, now: datetime | None = None) -> DetectionContext:
        return DetectionContext(
            hass=self.hass,
            world=self.rt.world,
            presence=self.rt.presence,
            settings=self.rt.settings,
            system=self.system,
            now=now or dt_util.utcnow(),
        )

    # ——— Scheduling ———
    def _rebuild_watch(self) -> None:
        ctx = self.context()
        watch: dict[str, set[str]] = {}
        for detector in self.detectors:
            for entity_id in detector.watched_entities(ctx):
                watch.setdefault(entity_id, set()).add(detector.key)
        self._watch = watch

    @callback
    def _on_state(self, event: Event) -> None:
        keys = self._watch.get(event.data["entity_id"])
        if keys:
            self._pending |= keys
            self._schedule_quick()

    @callback
    def schedule_all(self) -> None:
        self._pending |= {d.key for d in self.detectors}
        self._schedule_quick()

    def _schedule_quick(self) -> None:
        if self._cancel_quick is not None:
            return

        @callback
        def run(_now: datetime) -> None:
            self._cancel_quick = None
            keys, self._pending = self._pending, set()
            self.evaluate(keys)

        self._cancel_quick = async_call_later(self.hass, QUICK_DELAY, run)

    async def _tick(self, now: datetime) -> None:
        refresh = timedelta(seconds=int(self.rt.settings.get("detectors.system_refresh")))
        if self._system_due is None or now >= self._system_due:
            self._system_due = now + refresh
            await async_refresh(self.hass, self.system)
        self.evaluate({d.key for d in self.detectors})

    # ——— Evaluation ———
    @callback
    def evaluate(self, keys: set[str] | None = None) -> dict[str, Signal | None]:
        """Re-run the given detectors (all when None); returns and broadcasts the differences."""
        ctx = self.context()
        changes: dict[str, Signal | None] = {}
        for detector in self.detectors:
            if keys is not None and detector.key not in keys:
                continue
            try:
                found = detector.evaluate(ctx) if detector.enabled(ctx) else []
            except Exception:
                LOGGER.exception("Detector %s failed", detector.key)
                continue
            current = {s.id: s for s in found}
            previous = self._by_detector.get(detector.key, set())
            for sid in previous - set(current):
                self.signals.pop(sid, None)
                changes[sid] = None
            for sid, signal in current.items():
                if self.signals.get(sid) != signal:
                    self.signals[sid] = signal
                    changes[sid] = signal
            self._by_detector[detector.key] = set(current)
        if changes:
            for cb in list(self._listeners):
                try:
                    cb(changes)
                except Exception:
                    LOGGER.exception("Signal listener failed")
        return changes

    def diagnostics(self) -> dict[str, Any]:
        return {
            "detectors": [d.key for d in self.detectors],
            "signals": [s.as_dict() for s in self.signals.values()],
            "watched_entities": len(self._watch),
        }
