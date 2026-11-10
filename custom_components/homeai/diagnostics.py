"""Diagnostics: everything useful for a bug report, with secrets and personal names removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import VERSION

TO_REDACT = {"api_key", "token", "password", "secret", "user_id", "system_user_id", "base_url"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    rt = entry.runtime_data
    data: dict[str, Any] = {
        "version": VERSION,
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "subentries": [
            {"type": s.subentry_type, "title": s.title, "data": async_redact_data(dict(s.data), TO_REDACT)}
            for s in entry.subentries.values()
        ],
        "ready": rt.ready,
        "language": rt.language,
        "world": rt.world.summary(),
        "settings": rt.settings.export(),
        "settings_history": rt.settings.history(50),
        "journal": rt.journal.recent(200),
        "modules": {},
    }
    for name, module in rt.modules.items():
        diag = getattr(module, "diagnostics", None)
        if diag is not None:
            try:
                data["modules"][name] = async_redact_data(diag(), TO_REDACT)
            except Exception as err:
                data["modules"][name] = {"error": str(err)}
        else:
            data["modules"][name] = {"loaded": True}
    return data
