"""Every module with WebSocket commands or services. Imported in an executor thread at startup (they register
their handlers on import), so nothing is imported inside the event loop."""

from __future__ import annotations

from . import (  # noqa: F401 - imported for their registrations
    service_actions,
    service_ai,
    service_handlers,
    ws_actions,
    ws_ai,
    ws_chat,
    ws_learning,
    ws_rules,
    ws_settings,
    ws_situations,
)
