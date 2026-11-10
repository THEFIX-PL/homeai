"""P2 investigation: the agent reads the home with tools, may take a safe action through the policy, and answers
with the same assessment as triage (validated by the same guards)."""

from __future__ import annotations

from typing import Any

from ...situations.model import Situation
from ..agent import run_agent
from ..context import home_card, moment_card
from ..privacy import Privacy
from ..prompts import TRIAGE_SCHEMA, system_prompt
from ..tools import ToolContext
from .triage import situation_text, validate


async def investigate(ai: Any, s: Situation) -> dict[str, Any] | None:
    rt = ai.rt
    cfg = ai.first("p2")
    if cfg is None:
        return None
    privacy = Privacy(rt, ai.privacy_level(cfg))
    code = dict(s.assessment)
    ctx = ToolContext(rt, privacy, actor="ai", situation_id=s.id)
    result = await run_agent(
        ai,
        "p2",
        system=system_prompt(rt, "investigate"),
        messages=[
            {
                "role": "user",
                "content": "\n\n".join(
                    [
                        home_card(rt, privacy),
                        moment_card(rt, privacy),
                        situation_text(rt, s, privacy),
                        "Investigate, then answer with the JSON object.",
                    ]
                ),
            }
        ],
        ctx=ctx,
        toolset="investigate",
        schema=TRIAGE_SCHEMA,
        max_steps=int(rt.settings.get("ai.p2_max_steps")),
        purpose="investigate",
    )
    if result is None or not result.finished:
        return None
    assessment = validate(result.data, s, code, privacy)
    if assessment is not None and result.actions:
        assessment["actions"] = [{"what": a.get("what"), "status": a.get("status")} for a in result.actions][:5]
    return assessment
