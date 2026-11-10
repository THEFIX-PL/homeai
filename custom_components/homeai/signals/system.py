"""System snapshot: data outside the state machine (backups, log, automation traces), fetched periodically.

Detectors evaluate synchronously, so anything that needs an await is collected here first, at most every
`detectors.system_refresh` seconds, and read from the snapshot afterwards.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import LOGGER


@dataclass(slots=True)
class SystemSnapshot:
    fetched_at: datetime | None = None
    backup_agents_failed: list[str] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)


async def async_refresh(hass: HomeAssistant, snapshot: SystemSnapshot) -> None:
    """Fill the snapshot. Every part is optional and failures only leave that part empty."""
    try:
        if "backup" in hass.config.components:
            from homeassistant.components.backup.const import DATA_MANAGER

            if (manager := hass.data.get(DATA_MANAGER)) is not None:
                async with asyncio.timeout(60):
                    _, failed = await manager.async_get_backups()
                snapshot.backup_agents_failed = sorted(failed)
    except Exception as err:
        LOGGER.debug("Backup agents not read: %s", err)
    try:
        if (system_log := hass.data.get("system_log")) is not None:
            snapshot.log = system_log.records.to_list()
    except Exception as err:
        LOGGER.debug("System log not read: %s", err)
    try:
        if "trace" in hass.config.components:
            from homeassistant.components.trace.util import async_list_traces

            snapshot.traces = await async_list_traces(hass, "automation", None)
    except Exception as err:
        LOGGER.debug("Automation traces not read: %s", err)
    snapshot.fetched_at = dt_util.utcnow()
