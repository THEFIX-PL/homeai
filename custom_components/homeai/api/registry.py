"""WebSocket command modules (relative module names inside `api`), imported once at startup."""

from __future__ import annotations

MODULES: list[str] = ["ws_settings", "ws_situations", "ws_actions", "ws_ai", "ws_learning"]
