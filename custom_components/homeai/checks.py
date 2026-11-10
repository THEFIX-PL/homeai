"""What HomeAI lacks to work well, reported in Settings → Repairs (not errors: HomeAI runs anyway)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .notify.recipients import targets_for

INTERVAL = timedelta(hours=1)


class SetupChecks:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self._unsubs: list[Callable[[], None]] = []
        self._last: datetime | None = None

    async def async_setup(self) -> None:
        self._unsubs.append(self.rt.on_tick(self.tick))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def tick(self, now: datetime) -> None:
        if not self.rt.ready or (self._last is not None and now - self._last < INTERVAL):
            return
        self._last = now
        self.run()

    def problems(self) -> set[str]:
        found: set[str] = set()
        residents = self.rt.presence.residents()
        if not residents:
            found.add("no_residents")
        elif not any(targets_for(self.rt.hass, self.rt.settings, p.entity_id) for p in residents):
            found.add("no_phones")
        if not self.rt.world.areas:
            found.add("no_areas")
        return found

    def run(self) -> set[str]:
        hass = self.rt.hass
        found = self.problems()
        for issue in ("no_residents", "no_phones", "no_areas"):
            if issue in found:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=issue,
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, issue)
        return found
