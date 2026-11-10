"""Modules started after the world model, in data-flow order. Each entry: (name, factory(runtime)).

Situation processors run in the order their modules start: repair → triage → notifications, so triage sees
a repair that is about to be tried and nobody is bothered while the home fixes itself.
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


def _policy(rt: Any) -> Any:
    from .policy import Policy

    return Policy(rt)


def _executor(rt: Any) -> Any:
    from .actions.executor import Executor

    return Executor(rt)


def _approvals(rt: Any) -> Any:
    from .actions.approvals import Approvals

    return Approvals(rt)


def _repair(rt: Any) -> Any:
    from .repair.runner import RepairRunner

    return RepairRunner(rt)


def _adapters(rt: Any) -> Any:
    from .adapters.bridges import Adapters

    return Adapters(rt)


def _presence_exceptions(rt: Any) -> Any:
    from .schedule.presence import PresenceExceptions

    return PresenceExceptions(rt)


def _scheduler(rt: Any) -> Any:
    from .schedule.scheduler import Scheduler

    return Scheduler(rt)


def _ai(rt: Any) -> Any:
    from .ai.module import AIModule

    return AIModule(rt)


def _triage(rt: Any) -> Any:
    from .triage.engine import Triage

    return Triage(rt)


def _notify(rt: Any) -> Any:
    from .notify.router import NotificationRouter

    return NotificationRouter(rt)


STAGES: list[tuple[str, Callable[[Any], Any]]] = [
    ("signals", _signals),
    ("situations", _situations),
    ("policy", _policy),
    ("executor", _executor),
    ("approvals", _approvals),
    ("repair", _repair),
    ("triage", _triage),
    ("notify", _notify),
    ("adapters", _adapters),
    ("presence_exceptions", _presence_exceptions),
    ("scheduler", _scheduler),
    ("ai", _ai),
]
