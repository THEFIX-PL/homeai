"""Triage mission: P1 checks the rules' assessment of a new or unclear situation; P2 looks again when P1 is
unsure or the matter is serious; a strong disagreement is marked for the arbiter (P3).

Guards that no model can break: a safety matter is never lowered, a critical matter always needs someone, and
“nobody needed” is accepted only below high severity.
"""

from __future__ import annotations

from typing import Any

from ...signals.base import Category
from ...situations.model import Situation
from ..context import entity_lines, home_card, moment_card
from ..privacy import Privacy, clean
from ..prompts import TRIAGE_SCHEMA, system_prompt
from ..providers.base import AIRequest


def needs_triage(rt: Any, s: Situation) -> bool:
    settings = rt.settings
    if not settings.get("ai.triage_enabled") or s.primary is None:
        return False
    if s.assessment.get("assessed_by") in ("p1", "p2", "p3"):
        return False
    signals = list(s.signals.values())
    if any(x.kind == "external" for x in signals):
        return True
    if len({x.kind for x in signals}) > 1:
        return True
    if min(x.confidence for x in signals) < float(settings.get("ai.triage_confidence")):
        return True
    stats = rt.module("situations").stats.get(s.kind, {})
    return bool(settings.get("ai.triage_new_kinds")) and stats.get("opened", 0) <= 1


def situation_text(rt: Any, s: Situation, privacy: Privacy) -> str:
    lang = rt.language
    stats = rt.module("situations").stats.get(s.kind, {})
    if privacy.level == "minimal":  # titles carry real names and rooms
        p = s.primary
        where = privacy.area(str(p.data.get("where") or "")) if p else ""
        title = f"{s.kind}{' in ' + where if where else ''}"
    else:
        title = clean(s.title(lang), 150)
    lines = [
        "<situation>",
        f"Title: {title}",
        f"Kind: {s.kind}; category: {s.category}",
        f"Rules' assessment: severity {s.assessment.get('severity')}, who {s.assessment.get('who')}, "
        f"reasons {', '.join(s.assessment.get('reasons', []))}",
        f"Open since: {(s.opened_at or s.first_seen).isoformat(timespec='minutes')}",
        f"History of this kind: opened {stats.get('opened', 0)} times, dismissed as not a problem "
        f"{stats.get('dismissed', 0)} times",
    ]
    if privacy.level != "minimal" and (desc := s.description(lang)):
        lines.append(f"Description: {clean(desc, 300)}")
    if s.repair:
        lines.append(
            f"Repair: {s.repair.get('playbook')} — {s.repair.get('status')}, attempts {s.repair.get('attempts', 0)}"
        )
    if s.suppressed:
        lines.append(f"Explains {len(s.suppressed)} other signals")
    lines.append("</situation>")
    entities = entity_lines(rt, privacy, s.entities[:15])
    if entities:
        lines += ["<entities>", *entities, "</entities>"]
    return "\n".join(lines)


def validate(result: Any, s: Situation, code: dict[str, Any], privacy: Privacy) -> dict[str, Any] | None:
    """Clean a model's answer and apply the guards; None when it is unusable."""
    if not isinstance(result, dict):
        return None
    try:
        severity = int(result["severity"])
        who = str(result["who"])
        confidence = float(result["confidence"])
    except KeyError, TypeError, ValueError:
        return None
    if not 0 <= severity <= 4 or who not in ("nobody", "member", "admin", "service"):
        return None
    code_severity = int(code.get("severity", s.severity))
    if s.category == Category.SAFETY:
        severity = max(severity, code_severity)
    if code_severity >= 4:
        severity = 4
    if who == "nobody" and severity >= 3:
        who = str(code.get("fallback_who") or code.get("who") or "member")
        if who == "nobody":
            who = "member"
    steps = [privacy.restore(clean(x, 200)) for x in (result.get("steps") or []) if isinstance(x, str)][:3]
    return {
        "severity": severity,
        "who": who,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": privacy.restore(clean(result.get("reason", ""), 400)),
        "steps": steps,
    }


async def run_triage(ai: Any, s: Situation, tier: str = "p1") -> dict[str, Any] | None:
    rt = ai.rt
    cfg = ai.first(tier)
    if cfg is None:
        return None
    privacy = Privacy(rt, ai.privacy_level(cfg))
    code = dict(s.assessment)
    request = AIRequest(
        system=system_prompt(rt, "triage"),
        messages=[
            {
                "role": "user",
                "content": "\n\n".join(
                    [
                        home_card(rt, privacy),
                        moment_card(rt, privacy),
                        situation_text(rt, s, privacy),
                        "Check the assessment and answer with the JSON object.",
                    ]
                ),
            }
        ],
        schema=TRIAGE_SCHEMA,
        max_tokens=2048 if tier == "p1" else 8192,
        purpose="triage",
    )
    response = await ai.ask(tier, request, situation_id=s.id)
    if response is None:
        return None
    return validate(response.data, s, code, privacy)
