"""Custom detectors: rules people set up in the panel, without code or YAML.

A rule says: when an entity (or every entity with a label, in an area, of a domain) meets a condition for some
minutes — optionally only at night, only when nobody is home or only when someone is — open a situation with a
severity, a category, who is needed and advice. With `mode: each` every matching entity is a signal (one
situation per rule); with `mode: all` the rule fires only when all its entities meet the condition.
"""

from __future__ import annotations

import re
from typing import Any

from ...settings import SettingError
from ..base import Category, DetectionContext, Detector, Need, Signal
from .util import UNAVAILABLE, held_for, state

CONDITIONS = ("state", "not_state", "above", "below", "unavailable")
WHEN = ("always", "night", "away", "home")
MODES = ("each", "all")
ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_RULES = 100


def validate_rules(value: Any) -> list[dict[str, Any]]:
    """Normalise the rule list; raises SettingError with a short reason."""
    if not isinstance(value, list) or len(value) > MAX_RULES:
        raise SettingError(f"custom detectors: a list of up to {MAX_RULES} rules")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise SettingError(f"rule {n}: an object")
        rid = str(raw.get("id") or "")
        if not ID_RE.match(rid) or rid in seen:
            raise SettingError(f"rule {n}: id is unique, lowercase letters, digits and _")
        seen.add(rid)
        name = str(raw.get("name") or "").strip()[:100]
        if not name:
            raise SettingError(f"rule {n}: name")
        target = raw.get("target") or {}
        if not isinstance(target, dict):
            raise SettingError(f"rule {n}: target")
        entities = [e for e in target.get("entities") or [] if isinstance(e, str) and "." in e][:50]
        label, area, domain = (str(target.get(k) or "") or None for k in ("label", "area", "domain"))
        if not (entities or label or area or domain):
            raise SettingError(f"rule {n}: target needs entities, a label, an area or a domain")
        condition = raw.get("condition") or {}
        if not isinstance(condition, dict) or condition.get("type") not in CONDITIONS:
            raise SettingError(f"rule {n}: condition type is one of {', '.join(CONDITIONS)}")
        cond: dict[str, Any] = {"type": condition["type"]}
        if condition["type"] in ("above", "below"):
            try:
                cond["value"] = float(condition.get("value"))
            except (TypeError, ValueError) as err:
                raise SettingError(f"rule {n}: a number for {condition['type']}") from err
        elif condition["type"] in ("state", "not_state"):
            if not str(condition.get("value") or "").strip():
                raise SettingError(f"rule {n}: a state to compare")
            cond["value"] = str(condition["value"]).strip()[:100]
        try:
            minutes = int(raw.get("minutes", 0))
            severity = int(raw.get("severity", 1))
        except (TypeError, ValueError) as err:
            raise SettingError(f"rule {n}: minutes and severity are numbers") from err
        if not 0 <= minutes <= 10080 or not 0 <= severity <= 4:
            raise SettingError(f"rule {n}: minutes 0–10080, severity 0–4")
        try:
            category = Category(raw.get("category", "info"))
            need = Need(raw.get("need", "member"))
        except ValueError as err:
            raise SettingError(f"rule {n}: category or need") from err
        when = raw.get("when", "always")
        mode = raw.get("mode", "each")
        if when not in WHEN or mode not in MODES:
            raise SettingError(f"rule {n}: when is one of {', '.join(WHEN)}; mode each or all")
        out.append(
            {
                "id": rid,
                "name": name,
                "enabled": bool(raw.get("enabled", True)),
                "target": {"entities": entities, "label": label, "area": area, "domain": domain},
                "condition": cond,
                "minutes": minutes,
                "severity": severity,
                "category": str(category),
                "need": str(need),
                "advice": str(raw.get("advice") or "").strip()[:500],
                "when": when,
                "mode": mode,
            }
        )
    return out


def targets(ctx: DetectionContext, rule: dict[str, Any]) -> list[str]:
    world, target = ctx.world, rule["target"]
    found = set(target.get("entities") or [])
    label, area, domain = target.get("label"), target.get("area"), target.get("domain")
    if label or area or domain:
        for entity_id, info in world.entities.items():
            if label and label not in info.labels:
                continue
            if area and info.area_id != area:
                continue
            if domain and info.domain != domain:
                continue
            found.add(entity_id)
    return sorted(found)


def meets(ctx: DetectionContext, rule: dict[str, Any], entity_id: str) -> bool:
    s = state(ctx, entity_id)
    if s is None:
        return False
    cond = rule["condition"]
    kind = cond["type"]
    if kind == "unavailable":
        ok = s.state in UNAVAILABLE
    elif s.state in UNAVAILABLE:
        return False
    elif kind == "state":
        ok = s.state == cond["value"]
    elif kind == "not_state":
        ok = s.state != cond["value"]
    else:
        try:
            value = float(s.state)
        except ValueError:
            return False
        ok = value > cond["value"] if kind == "above" else value < cond["value"]
    return ok and held_for(s, ctx.now, rule["minutes"])


def active_now(ctx: DetectionContext, rule: dict[str, Any]) -> bool:
    when = rule["when"]
    if when == "night":
        return ctx.presence.day_part(ctx.now) == "night"
    if when == "away":
        return ctx.presence.everyone_away()
    if when == "home":
        return ctx.presence.someone_home()
    return True


class CustomDetector(Detector):
    key = "custom"

    def rules(self, ctx: DetectionContext) -> list[dict[str, Any]]:
        return [r for r in ctx.settings.get("detectors.custom") or [] if r.get("enabled")]

    def watched_entities(self, ctx: DetectionContext) -> set[str]:
        return {e for rule in self.rules(ctx) for e in targets(ctx, rule)}

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out: list[Signal] = []
        for rule in self.rules(ctx):
            if not active_now(ctx, rule):
                continue
            entities = targets(ctx, rule)
            matching = [e for e in entities if meets(ctx, rule, e)]
            if rule["mode"] == "all":
                if not entities or len(matching) != len(entities):
                    continue
                groups = [tuple(entities)]
            else:
                groups = [(e,) for e in matching]
            for group in groups:
                first = group[0]
                info = ctx.world.entity(first)
                name = ctx.world.display_name(first) if len(group) == 1 else ""
                title = f"{rule['name']}: {name}" if name else rule["name"]
                out.append(
                    Signal(
                        id=f"custom:{rule['id']}:{first if len(group) == 1 else 'all'}",
                        detector=self.key,
                        kind="custom",
                        category=Category(rule["category"]),
                        severity=rule["severity"],
                        entities=group,
                        device_id=info.device_id if info and len(group) == 1 else None,
                        area_id=info.area_id if info and len(group) == 1 else None,
                        data={
                            "title": title,
                            "description": rule["advice"],
                            "rule": rule["id"],
                            "name": name,
                            "where": ctx.world.area_name(info.area_id) if info else "",
                        },
                        need=Need(rule["need"]),
                        root=f"custom:{rule['id']}",
                    )
                )
        return out
