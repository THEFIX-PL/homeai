"""Config subentry flows for AI tiers (filled in by the AI stage)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentryFlow

SUBENTRY_FLOWS: dict[str, type[ConfigSubentryFlow]] = {}
