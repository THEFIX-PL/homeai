"""Modules started after the world model, in data-flow order. Each entry: (name, factory(runtime)).

Situation processors run in the order their modules start: triage → repair → notifications.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _signals(rt: Any) -> Any:
    from .signals.hub import SignalHub

    return SignalHub(rt)


def _situations(rt: Any) -> Any:
    from .situations.engine import SituationEngine

    return SituationEngine(rt)


def _triage(rt: Any) -> Any:
    from .triage.engine import Triage

    return Triage(rt)


def _notify(rt: Any) -> Any:
    from .notify.router import NotificationRouter

    return NotificationRouter(rt)


STAGES: list[tuple[str, Callable[[Any], Any]]] = [
    ("signals", _signals),
    ("situations", _situations),
    ("triage", _triage),
    ("notify", _notify),
]
