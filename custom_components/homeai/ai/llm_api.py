"""HomeAI tools for any conversation agent in Home Assistant (LLM API “HomeAI”).

Assistants built on other integrations can select this API and then read situations, the plan and states, and act
through HomeAI's policy in the speaking person's account.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
import probatio as pb

from ..const import DOMAIN
from .privacy import Privacy
from .tools import TOOLS, ToolContext, run_tool

EXPOSED = (
    "find_entities",
    "get_states",
    "list_situations",
    "get_situation",
    "get_plan",
    "call_service",
    "handle_situation",
    "add_to_plan",
)
PROMPT = (
    "HomeAI looks after this home: it tracks situations (problems, risks, maintenance), the home's plan and what it "
    "did. Use its tools to answer questions about the home's state and to act; actions go through HomeAI's policy "
    "and may need the person's confirmation (status needs_confirmation: ask, then call again with confirmed true) "
    "or someone's approval."
)


def _schema(json_schema: dict[str, Any]) -> pb.Schema:
    fields: dict[Any, Any] = {}
    required = set(json_schema.get("required", []))
    for name, prop in json_schema.get("properties", {}).items():
        key = pb.Required(name) if name in required else pb.Optional(name)
        kind = prop.get("type")
        if "enum" in prop:
            value: Any = pb.In(prop["enum"])
        elif kind == "integer":
            value = pb.Coerce(int)
        elif kind == "boolean":
            value = bool
        elif kind == "array":
            value = [str]
        elif kind == "object":
            value = dict
        else:
            value = str
        fields[key] = value
    return pb.Schema(fields)


class HomeAITool(llm.Tool):
    def __init__(self, rt: Any, name: str) -> None:
        tool = TOOLS[name]
        self.rt = rt
        self.name = f"homeai_{name}"
        self.description = tool.description
        self.parameters = _schema(tool.schema)
        self._tool = name

    async def async_call(self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext) -> Any:
        user_id = llm_context.context.user_id if llm_context.context else None
        ctx = ToolContext(self.rt, Privacy(self.rt), actor="person", user_id=user_id)
        text, _is_error = await run_tool(ctx, self._tool, dict(tool_input.tool_args))
        import json

        return json.loads(text) if text.startswith(("{", "[")) else {"result": text}


class HomeAIAPI(llm.API):
    def __init__(self, hass: HomeAssistant, rt: Any) -> None:
        self.hass = hass
        self.rt = rt
        self.id = DOMAIN
        self.name = "HomeAI"

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(
            api=self, api_prompt=PROMPT, llm_context=llm_context, tools=[HomeAITool(self.rt, n) for n in EXPOSED]
        )
