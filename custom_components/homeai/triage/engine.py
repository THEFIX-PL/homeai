"""Triage: how serious a situation is, how urgent, how sure HomeAI is, and who is needed.

The code decides first. Severity comes from the signals, adjusted by configured overrides, the “critical”
label, the context (safety and security matters while nobody is home are raised) and calibration from the
household's reactions (a kind dismissed again and again as “not a problem” is lowered — never safety).
Who is needed: nobody while a repair playbook is trying; otherwise what the signal says (a member for a
physical task, an administrator for configuration or sign-in, a technician). AI tiers may refine an assessment
later; their result is kept as long as the situation's signals do not change.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from ..signals.base import Category, Need
from ..situations.model import Situation

URGENCY_MINUTES: dict[str, int | None] = {
    Category.SAFETY: 0,
    Category.SECURITY: 5,
    Category.DAMAGE: 15,
    Category.SYSTEM: 60,
    Category.ENERGY: 60,
    Category.COMFORT: 120,
    Category.MAINTENANCE: 1440,
    Category.INFO: None,
}
RAISE_WHEN_AWAY = frozenset({Category.SAFETY, Category.SECURITY, Category.DAMAGE})
NEVER_LOWER = frozenset({Category.SAFETY})
AI_ASSESSORS = ("p1", "p2", "p3")


class Triage:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime

    async def async_setup(self) -> None:
        engine = self.rt.module("situations")
        engine.add_processor("triage", self.process)

    async def async_unload(self) -> None:
        return None

    async def process(self, event: str, s: Situation) -> None:
        if event in ("opened", "updated", "escalated"):
            s.assessment = self.assess(s)

    def assess(self, s: Situation) -> dict[str, Any]:
        p = s.primary
        if p is None:
            return {}
        signal_ids = sorted(s.signals)
        previous = s.assessment
        if previous.get("assessed_by") in AI_ASSESSORS and previous.get("signal_ids") == signal_ids:
            return previous  # an AI tier already looked at exactly this
        settings = self.rt.settings
        category = Category(p.category)
        severity = max(x.severity for x in s.signals.values())
        reasons: list[str] = [f"signal:{p.kind}"]

        overrides = settings.get("triage.severity_overrides") or {}
        if p.kind in overrides:
            severity = int(overrides[p.kind])
            reasons.append("override")
        world = self.rt.world
        if any(world.has_label(e, "label_critical") for e in s.entities) or (
            p.device_id and world.device_has_label(p.device_id, "label_critical")
        ):
            severity = 4
            reasons.append("critical_label")
        if category in RAISE_WHEN_AWAY and settings.get("triage.raise_when_away") and self.rt.presence.everyone_away():
            severity = min(4, severity + 1)
            reasons.append("everyone_away")
        if category not in NEVER_LOWER and settings.get("triage.calibration_enabled"):
            stats = self.rt.module("situations").stats.get(p.kind, {})
            opened = stats.get("opened", 0)
            if opened >= int(settings.get("triage.calibration_min_events")):
                ratio = stats.get("dismissed", 0) / max(opened, 1)
                if ratio >= float(settings.get("triage.calibration_dismiss_ratio")):
                    severity = max(0, severity - 1)
                    reasons.append("calibrated_down")

        need = p.need
        fallback = need
        if s.repair.get("status") in ("waiting", "trying", "verifying") and severity < 4:
            need = Need.NOBODY
            reasons.append("repairing")
        return {
            "severity": severity,
            "urgency_minutes": URGENCY_MINUTES.get(category),
            "confidence": min(x.confidence for x in s.signals.values()),
            "who": str(need),
            "fallback_who": str(fallback),
            "reasons": reasons,
            "assessed_by": "code",
            "assessed_at": dt_util.utcnow().isoformat(timespec="seconds"),
            "signal_ids": signal_ids,
        }

    def apply_ai(self, s: Situation, result: dict[str, Any], tier: str) -> None:
        """Store an AI tier's assessment (already validated) for the current set of signals."""
        s.assessment = {
            **self.assess(s),
            **{k: v for k, v in result.items() if k in ("severity", "who", "confidence", "reason", "steps", "dispute")},
            "assessed_by": tier,
            "assessed_at": dt_util.utcnow().isoformat(timespec="seconds"),
            "signal_ids": sorted(s.signals),
        }
