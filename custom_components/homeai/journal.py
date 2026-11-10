"""Journal: what HomeAI noticed, decided and did, and why — readable by everyone in the panel and diagnostics.

Every action, repair attempt, AI decision, notification and settings change leaves one entry. Entries are kept
for `general.journal_retention_days` and stored in `.storage/homeai.journal`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from .const import DOMAIN, LOGGER
from .settings import SettingsManager

STORAGE_KEY = f"{DOMAIN}.journal"
STORAGE_VERSION = 1
MAX_ENTRIES = 5000

KINDS = ("situation", "action", "repair", "decision", "notification", "approval", "setting", "ai", "schedule", "system")


class Journal:
    """Append-only log with retention."""

    def __init__(self, hass: HomeAssistant, settings: SettingsManager) -> None:
        self.hass = hass
        self.settings = settings
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.entries: list[dict[str, Any]] = []
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.entries = [e for e in data.get("entries") or [] if isinstance(e, dict) and e.get("ts")]
        self.prune()

    async def async_flush(self) -> None:
        await self._store.async_save({"entries": self.entries})

    @callback
    def add(
        self,
        kind: str,
        text: str,
        *,
        actor: str = "homeai",
        situation_id: str | None = None,
        result: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one event. `text` is already in the household's language."""
        entry = {
            "id": ulid_util.ulid_now().lower(),
            "ts": dt_util.utcnow().isoformat(timespec="seconds"),
            "kind": kind if kind in KINDS else "system",
            "actor": actor,
            "text": text,
            **({"situation_id": situation_id} if situation_id else {}),
            **({"result": result} if result else {}),
            **({"data": data} if data else {}),
        }
        self.entries.append(entry)
        del self.entries[:-MAX_ENTRIES]
        self._store.async_delay_save(lambda: {"entries": self.entries}, 5)
        for cb in list(self._listeners):
            try:
                cb(entry)
            except Exception:
                LOGGER.exception("Journal listener failed")
        return entry

    def prune(self) -> None:
        days = int(self.settings.get("general.journal_retention_days"))
        limit = (dt_util.utcnow() - timedelta(days=days)).isoformat(timespec="seconds")
        self.entries = [e for e in self.entries if e["ts"] >= limit][-MAX_ENTRIES:]

    def recent(
        self, limit: int = 100, *, kind: str | None = None, situation_id: str | None = None
    ) -> list[dict[str, Any]]:
        out = [
            e
            for e in reversed(self.entries)
            if (kind is None or e["kind"] == kind) and (situation_id is None or e.get("situation_id") == situation_id)
        ]
        return out[:limit]

    @callback
    def listen(self, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None
