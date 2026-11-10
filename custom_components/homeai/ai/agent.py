"""The tool loop: ask, run the tools the model calls, give back the results, until it answers.

One loop stays with one provider (message formats differ). Every step counts against budgets; the loop ends
after `max_steps` or when the model stops calling tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .providers.base import AIRequest
from .tools import SETS, TOOLS, ToolContext, run_tool


@dataclass(slots=True)
class AgentResult:
    text: str = ""
    data: Any = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    cost: float = 0.0
    source: str = ""
    finished: bool = False


async def run_agent(
    ai: Any,
    tier: str,
    *,
    system: str,
    messages: list[dict[str, Any]],
    ctx: ToolContext,
    toolset: str,
    schema: dict[str, Any] | None = None,
    max_steps: int = 8,
    max_tokens: int = 8192,
    purpose: str = "agent",
    source: str | None = None,
) -> AgentResult | None:
    tools = [TOOLS[name].spec() for name in SETS[toolset]]
    result = AgentResult(messages=list(messages), source=source or "")
    provider = None
    for step in range(max_steps):
        request = AIRequest(
            system=system, messages=result.messages, tools=tools, schema=schema, max_tokens=max_tokens, purpose=purpose
        )
        response = await ai.ask(tier, request, situation_id=ctx.situation_id, only=result.source or None)
        if response is None:
            return result if step else None
        result.source = response.source
        result.cost += response.cost
        result.steps = step + 1
        if provider is None:
            provider = await ai.provider(next(c for c in ai.tiers[tier] if c.subentry_id == response.source))
        if response.assistant_message is not None:
            result.messages.append(response.assistant_message)
        if not response.tool_calls:
            result.text, result.data, result.finished = response.text, response.data, True
            break
        outputs = []
        for call in response.tool_calls:  # sequentially: actions may depend on each other
            text, is_error = await run_tool(ctx, call.name, call.input)
            outputs.append((call, text, is_error))
        result.messages.extend(provider.tool_results(outputs))
    result.actions = ctx.actions
    return result
