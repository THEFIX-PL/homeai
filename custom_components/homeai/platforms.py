"""Entity platforms HomeAI sets up, in order."""

from __future__ import annotations

from homeassistant.const import Platform

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SWITCH,
    Platform.CALENDAR,
    Platform.CONVERSATION,
    Platform.SELECT,
    Platform.NUMBER,
]
