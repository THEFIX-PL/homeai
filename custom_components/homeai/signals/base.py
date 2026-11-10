"""Signals: observations with evidence, produced by detectors. A signal is not an alarm — situations are."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..settings import SettingsManager
    from ..world import Presence, WorldModel
    from .system import SystemSnapshot


class Category(StrEnum):
    SAFETY = "safety"  # people at risk: smoke, gas, CO, water
    SECURITY = "security"  # doors, locks, tampering
    DAMAGE = "damage"  # property at risk: freezing, flooding risk, overheating
    SYSTEM = "system"  # the smart home itself: integrations, devices, backups
    ENERGY = "energy"  # wasted energy: lights on in an empty home, window open while heating
    COMFORT = "comfort"  # air quality, temperature, humidity
    MAINTENANCE = "maintenance"  # batteries, filters, updates
    INFO = "info"


class Need(StrEnum):
    """Who is needed when the home cannot handle it itself."""

    NOBODY = "nobody"
    MEMBER = "member"  # anyone at home: a physical action (battery, water, window)
    ADMIN = "admin"  # configuration, sign-in, permissions
    SERVICE = "service"  # a technician or replacement part


class Severity(IntEnum):
    LOG = 0  # journal only
    NOTICE = 1  # today: screen, digest
    ATTENTION = 2  # now: one push
    URGENT = 3  # now, escalating
    CRITICAL = 4  # people or property at risk: everyone, repeated until acknowledged


@dataclass(slots=True, frozen=True)
class Signal:
    """One observation. `id` is unique across detectors and stable while the condition lasts."""

    id: str
    detector: str
    kind: str  # text key under `signals|<kind>` in i18n
    category: Category
    severity: int
    entities: tuple[str, ...] = ()
    device_id: str | None = None
    area_id: str | None = None
    since: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)  # placeholders for texts
    need: Need = Need.MEMBER
    root: str | None = None  # correlation key: signals with the same root form one situation
    tags: frozenset[str] = frozenset()  # e.g. {"zigbee"}, {"cloud"}
    suppresses: frozenset[str] = frozenset()  # tags of signals this one explains (internet down → "cloud")
    repair: dict[str, Any] | None = None  # {"playbook": key, ...params}
    action: dict[str, Any] | None = None  # suggested quick action {"service": "...", "data": {...}}
    confidence: float = 1.0

    @property
    def group(self) -> str:
        return self.root or self.id

    def with_severity(self, severity: int) -> Signal:
        return replace(self, severity=max(0, min(4, severity)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "detector": self.detector,
            "kind": self.kind,
            "category": str(self.category),
            "severity": self.severity,
            "entities": list(self.entities),
            "device_id": self.device_id,
            "area_id": self.area_id,
            "since": self.since.isoformat() if self.since else None,
            "data": self.data,
            "need": str(self.need),
            "root": self.root,
            "tags": sorted(self.tags),
            "repair": self.repair,
            "action": self.action,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Signal:
        from homeassistant.util import dt as dt_util

        return cls(
            id=d["id"],
            detector=d.get("detector", "stored"),
            kind=d.get("kind", "external"),
            category=Category(d.get("category", "info")),
            severity=int(d.get("severity", 1)),
            entities=tuple(d.get("entities") or ()),
            device_id=d.get("device_id"),
            area_id=d.get("area_id"),
            since=dt_util.parse_datetime(d["since"]) if d.get("since") else None,
            data=dict(d.get("data") or {}),
            need=Need(d.get("need", "member")),
            root=d.get("root"),
            tags=frozenset(d.get("tags") or ()),
            repair=d.get("repair"),
            action=d.get("action"),
            confidence=float(d.get("confidence", 1.0)),
        )


@dataclass(slots=True)
class DetectionContext:
    """What detectors read. Detectors never call services; they only look."""

    hass: HomeAssistant
    world: WorldModel
    presence: Presence
    settings: SettingsManager
    system: SystemSnapshot
    now: datetime


class Detector:
    """Base class. `evaluate` returns the complete current list of this detector's signals."""

    key: str = ""
    # Roles whose state changes should trigger a quick re-evaluation (besides the periodic one).
    roles: tuple[str, ...] = ()
    # Extra entity ids (from settings) whose changes trigger re-evaluation.
    watch_settings: tuple[str, ...] = ()

    def enabled(self, ctx: DetectionContext) -> bool:
        key = f"detectors.{self.key}.enabled"
        return bool(ctx.settings.get(key)) if key in ctx.settings.registry else True

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:  # pragma: no cover - abstract
        raise NotImplementedError

    def watched_entities(self, ctx: DetectionContext) -> set[str]:
        out = ctx.world.with_role(*self.roles) if self.roles else set()
        for key in self.watch_settings:
            value = ctx.settings.get(key)
            if isinstance(value, str) and value:
                out.add(value)
            elif isinstance(value, list):
                out.update(v for v in value if isinstance(v, str))
        return out
