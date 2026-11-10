"""HomeAI runtime: owns every module of one config entry and their lifecycle.

Start order follows the data flow: settings → world → detection → situations → notifications → actions → AI.
The AI layer starts last and in its own try: a broken provider never stops the core.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.util import dt as dt_util

from . import i18n
from .const import LOGGER
from .journal import Journal
from .settings import SettingsManager, build_registry
from .world import Presence, WorldModel

if TYPE_CHECKING:
    pass

TickHandler = Callable[[datetime], Awaitable[None] | None]


class HomeAIRuntime:
    """Everything HomeAI runs for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.settings = SettingsManager(hass, build_registry())
        self.journal = Journal(hass, self.settings)
        self.world = WorldModel(hass, self.settings)
        self.presence = Presence(hass, self.world, self.settings)
        self.started_at = dt_util.utcnow()
        self.ready = False  # True after the startup grace period: integrations had time to come up
        self._tick_handlers: list[TickHandler] = []
        self._unsubs: list[Callable[[], None]] = []
        self._stoppers: list[Callable[[], Awaitable[None]]] = []
        # Modules added by later stages register themselves here (situations, notify, policy, ai…).
        self.modules: dict[str, Any] = {}

    # ——— Lifecycle ———
    async def async_setup(self) -> None:
        await i18n.async_preload(self.hass)
        await self.settings.async_load()
        self._apply_initial_settings()
        await self.journal.async_load()
        await self.world.async_start()
        self._stoppers.append(self.world.async_stop)
        await self._setup_modules()
        self._start_timers()

    async def _setup_modules(self) -> None:
        """Hook for later stages; each module is set up in its own try so one failure is contained."""
        from .stages import STAGES

        for name, factory in STAGES:
            try:
                module = factory(self)
                await module.async_setup()
            except Exception:
                LOGGER.exception("HomeAI module %s failed to start", name)
                continue
            self.modules[name] = module
            self._stoppers.append(module.async_unload)

    def _apply_initial_settings(self) -> None:
        """Values chosen in the setup wizard are written into the settings store once."""
        initial = self.entry.data.get("initial_settings")
        if not initial or self.entry.data.get("initial_settings_applied"):
            return
        for key, values in initial.items():
            if key == "overrides":
                for skey, inner in values.items():
                    for k, v in inner.items():
                        self.settings.set(k, v, skey=skey, user="setup", confirmed=True)
            else:
                self.settings.set(key, values, user="setup", confirmed=True)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, "initial_settings_applied": True}
        )

    def _start_timers(self) -> None:
        interval = timedelta(seconds=int(self.settings.get("general.tick_seconds")))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, interval))
        if self.hass.state is CoreState.running:
            self._schedule_ready()
        else:

            @callback
            def started(_event: Event) -> None:
                self._schedule_ready()

            self._unsubs.append(self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, started))

    @callback
    def _schedule_ready(self) -> None:
        @callback
        def ready(_now: datetime) -> None:
            self.ready = True
            self.hass.async_create_task(self._run_tick(dt_util.utcnow()))

        grace = int(self.settings.get("general.startup_grace"))
        self._unsubs.append(async_call_later(self.hass, grace, ready))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for stop in reversed(self._stoppers):
            try:
                await stop()
            except Exception:
                LOGGER.exception("HomeAI module failed to stop")
        await self.settings.async_flush()
        await self.journal.async_flush()

    # ——— Periodic work ———
    @callback
    def on_tick(self, handler: TickHandler) -> Callable[[], None]:
        self._tick_handlers.append(handler)
        return lambda: self._tick_handlers.remove(handler) if handler in self._tick_handlers else None

    @callback
    def _tick(self, now: datetime) -> None:
        self.hass.async_create_task(self._run_tick(now))

    async def _run_tick(self, now: datetime) -> None:
        for handler in list(self._tick_handlers):
            try:
                result = handler(now)
                if result is not None:
                    await result
            except Exception:
                LOGGER.exception("HomeAI periodic task failed")
        self.journal.prune()

    # ——— Helpers for modules ———
    @property
    def language(self) -> str:
        return i18n.resolve_language(self.hass, str(self.settings.get("general.language")))

    def text(self, path: str, **placeholders: Any) -> str:
        return i18n.text(self.language, path, **placeholders)

    def module(self, name: str) -> Any:
        return self.modules.get(name)
