"""Norms per entity and hour of the week, from the recorder's long-term statistics.

For measuring sensors (temperature, humidity, CO₂, power) HomeAI keeps the mean and spread of each of the 168
hours of the week over the last weeks. A value far outside its hour's norm for a while becomes an `anomaly`
signal of low certainty, so the AI tier looks at it before anyone is bothered.
"""

from __future__ import annotations

from datetime import timedelta
import math
from typing import Any

from homeassistant.util import dt as dt_util

from ..signals.base import Category, DetectionContext, Detector, Need, Signal
from ..signals.detectors.util import held_for, setting, state
from ..world import Role

ROLES = (Role.TEMPERATURE, Role.HUMIDITY, Role.CO2, Role.POWER)
CATEGORY = {Role.POWER: Category.ENERGY}


def hour_of_week(ts: float) -> int:
    local = dt_util.as_local(dt_util.utc_from_timestamp(ts))
    return local.weekday() * 24 + local.hour


def summarise(rows: list[dict[str, Any]], min_samples: int) -> dict[str, list[float]] | None:
    """168 buckets of [mean, std, n] from hourly statistic rows."""
    buckets: list[list[float]] = [[] for _ in range(168)]
    for row in rows:
        mean = row.get("mean")
        if mean is None:
            continue
        buckets[hour_of_week(float(row["start"]))].append(float(mean))
    out = []
    filled = 0
    for values in buckets:
        if len(values) < 2:
            out.append([math.nan, math.nan, float(len(values))])
            continue
        m = sum(values) / len(values)
        sd = math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))
        out.append([m, sd, float(len(values))])
        filled += len(values)
    return {"buckets": out} if filled >= min_samples else None


class Baselines:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.norms: dict[str, dict[str, Any]] = {}
        self.refreshed: str | None = None

    def candidates(self) -> list[str]:
        world = self.rt.world
        return sorted(e for e in world.with_role(*ROLES) if not world.has_label(e, "label_ignore"))

    async def refresh(self) -> int:
        """Recompute norms (runs in the recorder's executor). Returns how many entities have a norm."""
        hass = self.rt.hass
        if "recorder" not in hass.config.components:
            return 0
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        ids = set(self.candidates())
        if not ids:
            return 0
        weeks = int(self.rt.settings.get("learning.baseline_weeks"))
        start = dt_util.utcnow() - timedelta(weeks=weeks)
        rows = await get_instance(hass).async_add_executor_job(
            statistics_during_period, hass, start, None, ids, "hour", None, {"mean"}
        )
        min_samples = int(self.rt.settings.get("learning.min_samples"))
        norms = {}
        for entity_id, entity_rows in rows.items():
            summary = summarise(list(entity_rows), min_samples)
            if summary is not None:
                norms[entity_id] = summary
        self.norms = norms
        self.refreshed = dt_util.utcnow().isoformat(timespec="seconds")
        return len(norms)

    def norm(self, entity_id: str, now: Any = None) -> tuple[float, float] | None:
        data = self.norms.get(entity_id)
        if data is None:
            return None
        m, sd, n = data["buckets"][hour_of_week((now or dt_util.utcnow()).timestamp())]
        if math.isnan(m) or n < 2:
            return None
        return m, sd


class AnomalyDetector(Detector):
    key = "anomaly"
    roles = ROLES

    def __init__(self, baselines: Baselines) -> None:
        self.baselines = baselines

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out = []
        sigma = float(ctx.settings.get("learning.anomaly_sigma"))
        for entity_id in self.baselines.norms:
            info = ctx.world.entity(entity_id)
            value = ctx.world.value(entity_id)
            norm = self.baselines.norm(entity_id, ctx.now)
            if info is None or value is None or norm is None:
                continue
            mean, sd = norm
            spread = max(sd, abs(mean) * 0.05, 0.5)
            if abs(value - mean) <= sigma * spread:
                continue
            s = state(ctx, entity_id)
            if not held_for(s, ctx.now, float(setting(ctx, "learning.anomaly_minutes", entity_id))):
                continue
            role = next((r for r in ROLES if r in info.roles), Role.TEMPERATURE)
            out.append(
                Signal(
                    id=f"anomaly:{entity_id}",
                    detector=self.key,
                    kind="anomaly",
                    category=CATEGORY.get(role, Category.COMFORT),
                    severity=int(setting(ctx, "learning.anomaly_severity", entity_id)),
                    entities=(entity_id,),
                    device_id=info.device_id,
                    area_id=info.area_id,
                    since=s.last_changed if s else None,
                    data={
                        "name": ctx.world.display_name(entity_id),
                        "where": ctx.world.area_name(info.area_id),
                        "value": f"{value:g}{info.unit or ''}",
                        "usual": f"{mean:.1f}{info.unit or ''}",
                    },
                    need=Need.MEMBER,
                    confidence=0.6,
                )
            )
        return out
