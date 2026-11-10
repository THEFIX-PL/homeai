"""Situation: one matter in the home, made of correlated signals, with a lifecycle and a history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from homeassistant.util import dt as dt_util

from .. import i18n
from ..signals.base import Signal


class Phase(StrEnum):
    PENDING = "pending"  # seen, waiting to prove it is not a flicker (or for the startup grace period)
    OPEN = "open"  # announced: triage, repair and notifications act on it
    CLEARING = "clearing"  # signals gone, waiting to be sure before closing
    RESOLVED = "resolved"


EVENTS = ("opened", "updated", "escalated", "acknowledged", "snoozed", "handled", "dismissed", "resolved")


@dataclass(slots=True)
class Situation:
    id: str
    group: str
    first_seen: datetime
    phase: Phase = Phase.PENDING
    signals: dict[str, Signal] = field(default_factory=dict)
    suppressed: dict[str, Signal] = field(default_factory=dict)
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    clearing_since: datetime | None = None
    resolved_at: datetime | None = None
    assessment: dict[str, Any] = field(default_factory=dict)
    acked_by: str | None = None
    acked_at: datetime | None = None
    snoozed_until: datetime | None = None
    handled_by: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    repair: dict[str, Any] = field(default_factory=dict)  # state owned by the repair runner
    notify: dict[str, Any] = field(default_factory=dict)  # state owned by the notification router

    # ——— Derived ———
    @property
    def primary(self) -> Signal | None:
        pool = list(self.signals.values()) or list(self.suppressed.values())
        if not pool:
            return None
        return sorted(pool, key=lambda s: (-s.severity, s.since or self.first_seen, s.id))[0]

    @property
    def kind(self) -> str:
        p = self.primary
        return p.kind if p else "unknown"

    @property
    def category(self) -> str:
        p = self.primary
        return str(p.category) if p else "info"

    @property
    def severity(self) -> int:
        if "severity" in self.assessment:
            return int(self.assessment["severity"])
        return max((s.severity for s in self.signals.values()), default=0)

    @property
    def entities(self) -> list[str]:
        out: list[str] = []
        for s in self.signals.values():
            out.extend(e for e in s.entities if e not in out)
        return out

    @property
    def active(self) -> bool:
        return self.phase in (Phase.OPEN, Phase.CLEARING)

    def muted(self, now: datetime | None = None) -> bool:
        """Acknowledged or snoozed: notifications stop until something changes."""
        now = now or dt_util.utcnow()
        if self.snoozed_until and self.snoozed_until > now:
            return True
        return self.acked_at is not None

    def log(self, event: str, text: str = "", **data: Any) -> None:
        self.history.append(
            {"ts": dt_util.utcnow().isoformat(timespec="seconds"), "event": event, "text": text, **data}
        )
        del self.history[:-100]

    # ——— Texts ———
    def title(self, lang: str) -> str:
        p = self.primary
        if p is None:
            return ""
        if p.kind in ("external", "custom"):
            return str(p.data.get("title", ""))
        same = [s for s in self.signals.values() if s.kind == p.kind]
        if len(same) > 1 and i18n.has(lang, f"signals|{p.kind}|title_many"):
            names = [str(s.data.get("name") or s.data.get("where") or "") for s in same]
            return i18n.text(lang, f"signals|{p.kind}|title_many", count=len(same), names=names, **_data(p))
        title = i18n.text(lang, f"signals|{p.kind}|title", **_data(p))
        others = len(self.signals) - 1
        return title if others <= 0 else i18n.text(lang, "situation|and_more", title=title, count=others)

    def description(self, lang: str) -> str:
        p = self.primary
        if p is None:
            return ""
        if p.kind in ("external", "custom"):
            return str(p.data.get("description", ""))
        key = f"signals|{p.kind}|description"
        if (variant := p.data.get("variant")) and i18n.has(lang, f"{key}_{variant}"):
            key = f"{key}_{variant}"  # e.g. no backup has ever succeeded
        return i18n.text(lang, key, **_data(p)) if i18n.has(lang, key) else ""

    # ——— Serialisation ———
    def as_dict(self, lang: str | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "group": self.group,
            "phase": str(self.phase),
            "kind": self.kind,
            "category": self.category,
            "severity": self.severity,
            "first_seen": _iso(self.first_seen),
            "opened_at": _iso(self.opened_at),
            "updated_at": _iso(self.updated_at),
            "clearing_since": _iso(self.clearing_since),
            "resolved_at": _iso(self.resolved_at),
            "signals": [s.as_dict() for s in self.signals.values()],
            "suppressed": [s.as_dict() for s in self.suppressed.values()],
            "assessment": self.assessment,
            "acked_by": self.acked_by,
            "acked_at": _iso(self.acked_at),
            "snoozed_until": _iso(self.snoozed_until),
            "handled_by": self.handled_by,
            "history": self.history,
            "repair": self.repair,
            "notify": self.notify,
        }
        if lang:
            d["title"] = self.title(lang)
            d["description"] = self.description(lang)
            d["entities"] = self.entities
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Situation:
        parse = dt_util.parse_datetime
        s = cls(
            id=d["id"],
            group=d["group"],
            first_seen=parse(d["first_seen"]) or dt_util.utcnow(),
            phase=Phase(d.get("phase", "open")),
        )
        s.signals = {x["id"]: Signal.from_dict(x) for x in d.get("signals") or []}
        s.suppressed = {x["id"]: Signal.from_dict(x) for x in d.get("suppressed") or []}
        for key in ("opened_at", "updated_at", "clearing_since", "resolved_at", "acked_at", "snoozed_until"):
            setattr(s, key, parse(d[key]) if d.get(key) else None)
        s.assessment = dict(d.get("assessment") or {})
        s.acked_by = d.get("acked_by")
        s.handled_by = d.get("handled_by")
        s.history = list(d.get("history") or [])
        s.repair = dict(d.get("repair") or {})
        s.notify = dict(d.get("notify") or {})
        return s


def _iso(t: datetime | None) -> str | None:
    return t.isoformat(timespec="seconds") if t else None


def _data(signal: Signal) -> dict[str, Any]:
    data = dict(signal.data)
    data.setdefault("name", "")
    data.setdefault("where", "")
    return data
