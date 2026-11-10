"""Tools for AI tiers. Reads are filtered by privacy; every change goes through the executor and its policy,
in the context of the person who asked (chat) or of HomeAI (missions).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
import json
from typing import Any

from homeassistant.util import dt as dt_util

from ..policy import ActionRequest
from .privacy import Privacy, clean
from .providers.base import ToolSpec

MAX_RESULT = 6000


@dataclass(slots=True)
class ToolContext:
    rt: Any
    privacy: Privacy
    actor: str = "ai"  # "ai" (a mission) or "person" (chat)
    user_id: str | None = None
    situation_id: str | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Handler
    changes: bool = False  # goes through the executor

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.schema)


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


STR = {"type": "string"}
STRS = {"type": "array", "items": {"type": "string"}}


# ——— Reading ———
async def find_entities(ctx: ToolContext, args: dict[str, Any]) -> Any:
    world, query = ctx.rt.world, str(args.get("query") or "").lower()
    area_q, domain = str(args.get("area") or "").lower(), args.get("domain")
    out = []
    for entity_id, info in sorted(world.entities.items()):
        if domain and info.domain != domain:
            continue
        if not ctx.privacy.allowed(entity_id):
            continue
        area = world.area_name(info.area_id)
        name = world.display_name(entity_id)
        if query and query not in name.lower() and query not in entity_id:
            continue
        if area_q and area_q not in area.lower():
            continue
        state = ctx.rt.hass.states.get(entity_id)
        out.append(
            {
                "entity_id": entity_id,
                "name": ctx.privacy.entity_name(entity_id),
                "area": ctx.privacy.area(area),
                "state": clean(state.state, 40) if state else None,
            }
        )
        if len(out) >= min(int(args.get("limit") or 30), 100):
            break
    return out


async def get_states(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from .context import KEEP_ATTRIBUTES

    out = []
    for entity_id in (args.get("entity_ids") or [])[:30]:
        state = ctx.rt.hass.states.get(entity_id)
        if state is None or not ctx.privacy.allowed(entity_id):
            out.append({"entity_id": entity_id, "error": "not_available"})
            continue
        out.append(
            {
                "entity_id": entity_id,
                "name": ctx.privacy.entity_name(entity_id),
                "state": clean(state.state, 60),
                "since": state.last_changed.isoformat(timespec="minutes"),
                "attributes": ctx.privacy.attributes(dict(state.attributes), (*KEEP_ATTRIBUTES, "friendly_name")),
            }
        )
    return out


async def get_history(ctx: ToolContext, args: dict[str, Any]) -> Any:
    entity_id = str(args.get("entity_id") or "")
    if not ctx.privacy.allowed(entity_id) or ctx.rt.hass.states.get(entity_id) is None:
        return {"error": "not_available"}
    if "recorder" not in ctx.rt.hass.config.components:
        return {"error": "no_recorder"}
    from homeassistant.components.recorder import get_instance, history

    hours = max(1, min(int(args.get("hours") or 24), 168))
    start = dt_util.utcnow() - timedelta(hours=hours)
    states = await get_instance(ctx.rt.hass).async_add_executor_job(
        history.state_changes_during_period, ctx.rt.hass, start, None, entity_id, True, True, 100
    )
    return [
        {"at": s.last_changed.isoformat(timespec="minutes"), "state": clean(s.state, 40)}
        for s in reversed(states.get(entity_id, []))
    ]


async def list_situations(ctx: ToolContext, args: dict[str, Any]) -> Any:
    engine = ctx.rt.module("situations")
    return [
        {
            "situation_id": s.id,
            "title": clean(s.title(ctx.rt.language), 120) if ctx.privacy.level != "minimal" else s.kind,
            "kind": s.kind,
            "severity": s.severity,
            "category": s.category,
            "who": s.assessment.get("who"),
            "acknowledged": s.acked_at is not None,
            "repair": s.repair.get("status"),
        }
        for s in engine.open()
    ]


async def get_situation(ctx: ToolContext, args: dict[str, Any]) -> Any:
    engine = ctx.rt.module("situations")
    s = engine.get(str(args.get("situation_id") or ""))
    if s is None:
        return {"error": "not_found"}
    from .missions.triage import situation_text

    return {"text": situation_text(ctx.rt, s, ctx.privacy), "history": s.history[-15:], "assessment": s.assessment}


async def get_journal(ctx: ToolContext, args: dict[str, Any]) -> Any:
    if ctx.privacy.level == "minimal":
        return {"error": "not_available_with_minimal_privacy"}
    return [
        {"at": e["ts"], "kind": e["kind"], "text": clean(e["text"], 200)}
        for e in ctx.rt.journal.recent(int(args.get("limit") or 20))
    ]


async def get_system_log(ctx: ToolContext, args: dict[str, Any]) -> Any:
    hub = ctx.rt.module("signals")
    return {"log": hub.system.log[:20], "failed_automations": hub.system.traces[:20]} if hub else {}


async def get_plan(ctx: ToolContext, args: dict[str, Any]) -> Any:
    scheduler = ctx.rt.module("scheduler")
    now = dt_util.utcnow()
    days = max(1, min(int(args.get("days") or 7), 60))
    return [
        {"at": dt_util.as_local(t).isoformat(timespec="minutes"), "entry_id": e["id"], "title": clean(e["title"], 120)}
        for t, e in scheduler.occurrences(now, now + timedelta(days=days))
    ][:100]


# ——— Changing (through the executor) ———
async def _execute(ctx: ToolContext, request: ActionRequest) -> dict[str, Any]:
    request.actor = "person" if ctx.actor == "person" else "ai"
    request.user_id = ctx.user_id if ctx.actor == "person" else None
    request.situation_id = request.situation_id or ctx.situation_id
    result = await ctx.rt.module("executor").execute(request)
    record = {"what": ctx.rt.module("executor").describe(request), **result.as_dict()}
    ctx.actions.append(record)
    out: dict[str, Any] = {"status": result.status, "risk": result.risk, "message": result.message}
    if result.approval_id:
        out["approval_id"] = result.approval_id
    if result.data is not None:
        out["data"] = result.data
    return out


async def call_service(ctx: ToolContext, args: dict[str, Any]) -> Any:
    domain, _, service = str(args.get("service") or "").partition(".")
    return await _execute(
        ctx,
        ActionRequest(
            domain,
            service,
            dict(args.get("data") or {}),
            entity_ids=list(args.get("entity_ids") or []),
            reason=str(args.get("reason") or ""),
            confirmed=bool(args.get("confirmed")),
        ),
    )


async def edit_config(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await _execute(
        ctx,
        ActionRequest(
            "config",
            str(args.get("operation") or ""),
            dict(args.get("data") or {}),
            reason=str(args.get("reason") or ""),
            confirmed=bool(args.get("confirmed")),
        ),
    )


async def add_to_plan(ctx: ToolContext, args: dict[str, Any]) -> Any:
    from ..schedule.scheduler import PlanError

    raw = {k: v for k, v in args.items() if k in ("title", "when", "reminder", "to", "skip_when_away", "action")}
    try:
        entry = await ctx.rt.module("scheduler").save(raw, ctx.user_id if ctx.actor == "person" else None)
    except PlanError as err:
        return {"error": str(err)}
    ctx.actions.append({"what": f"plan: {entry['title']}", "status": "done"})
    return {"entry_id": entry["id"], "title": entry["title"]}


async def handle_situation(ctx: ToolContext, args: dict[str, Any]) -> Any:
    engine = ctx.rt.module("situations")
    sid, action = str(args.get("situation_id") or ""), args.get("action")
    who = "HomeAI"
    if ctx.user_id:
        who = next((p.name for p in ctx.rt.world.persons.values() if p.user_id == ctx.user_id), who)
    if action == "acknowledge":
        s = await engine.acknowledge(sid, who)
    elif action == "handle":
        s = await engine.handle(sid, who)
    elif action == "snooze":
        s = await engine.snooze(sid, int(args.get("minutes") or 60), who)
    elif action == "dismiss" and ctx.actor == "person":
        s = await engine.dismiss(sid, who)
    else:
        return {"error": "not_allowed"}
    return {"done": s is not None}


async def remember(ctx: ToolContext, args: dict[str, Any]) -> Any:
    memory = ctx.rt.module("memory")
    if memory is None:
        return {"error": "memory_off"}
    scope = "home"
    if args.get("about_me") and ctx.user_id:
        person = next((p for p in ctx.rt.world.persons.values() if p.user_id == ctx.user_id), None)
        scope = f"person:{person.entity_id}" if person else "home"
    source = "person" if ctx.actor == "person" else "ai"
    fact = memory.add(ctx.privacy.restore(str(args.get("fact") or "")), scope=scope, source=source, author=ctx.user_id)
    return {"remembered": fact["text"], "approved": fact["approved"]}


async def recall(ctx: ToolContext, args: dict[str, Any]) -> Any:
    memory = ctx.rt.module("memory")
    if memory is None:
        return []
    facts = memory.search(str(args.get("words") or ""), limit=10)
    return [{"fact": clean(f["text"], 300), "scope": f["scope"].split(":", 1)[0]} for f in facts]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "find_entities",
            "Find entities by words in their name, by area or by domain.",
            _obj({"query": STR, "area": STR, "domain": STR, "limit": {"type": "integer"}}),
            find_entities,
        ),
        Tool(
            "get_states",
            "Current state and key attributes of entities.",
            _obj({"entity_ids": STRS}, ["entity_ids"]),
            get_states,
        ),
        Tool(
            "get_history",
            "State changes of one entity over the last hours (up to 168).",
            _obj({"entity_id": STR, "hours": {"type": "integer"}}, ["entity_id"]),
            get_history,
        ),
        Tool("list_situations", "Open situations HomeAI is tracking.", _obj({}), list_situations),
        Tool(
            "get_situation",
            "Details of one situation: signals, entities, history, assessment.",
            _obj({"situation_id": STR}, ["situation_id"]),
            get_situation,
        ),
        Tool(
            "get_journal",
            "Recent entries of HomeAI's journal (what happened and what HomeAI did).",
            _obj({"limit": {"type": "integer"}}),
            get_journal,
        ),
        Tool(
            "get_system_log",
            "Recent errors in Home Assistant's log and automations whose last run failed.",
            _obj({}),
            get_system_log,
        ),
        Tool("get_plan", "Upcoming entries of the home's plan.", _obj({"days": {"type": "integer"}}), get_plan),
        Tool(
            "call_service",
            "Run a Home Assistant action (service) through HomeAI's policy. The result status is done, unverified, "
            "needs_confirmation (ask the person, then call again with confirmed true), pending_approval (someone was "
            "asked), observed (HomeAI is only observing), denied or failed. Never say something was done unless the "
            "status is done or unverified.",
            _obj(
                {
                    "service": STR,
                    "entity_ids": STRS,
                    "data": {"type": "object"},
                    "reason": STR,
                    "confirmed": {"type": "boolean"},
                },
                ["service", "reason"],
            ),
            call_service,
            changes=True,
        ),
        Tool(
            "edit_config",
            "Change Home Assistant configuration through its editors: operation is one of automation_get/save/delete, "
            "script_get/save/delete, scene_get/save/delete (data: id, config), helper_list/save/delete (data: domain, "
            "item_id, fields), label_save, area_save, dashboard_get/save. Saves need an administrator; deletions are "
            "destructive.",
            _obj(
                {"operation": STR, "data": {"type": "object"}, "reason": STR, "confirmed": {"type": "boolean"}},
                ["operation", "data", "reason"],
            ),
            edit_config,
            changes=True,
        ),
        Tool(
            "add_to_plan",
            "Add an action or a reminder to the home's plan. when: {kind: once|daily|weekly|sun, time: HH:MM, date, "
            "days: [0-6, Monday is 0], event: sunrise|sunset, offset: minutes}. Either action {service, entity_ids, "
            "data} or reminder (text).",
            _obj(
                {
                    "title": STR,
                    "when": {"type": "object"},
                    "reminder": STR,
                    "to": STR,
                    "skip_when_away": {"type": "boolean"},
                    "action": {"type": "object"},
                },
                ["when"],
            ),
            add_to_plan,
            changes=True,
        ),
        Tool(
            "handle_situation",
            "Acknowledge, take, snooze or (for people) dismiss a situation.",
            _obj(
                {
                    "situation_id": STR,
                    "action": {"type": "string", "enum": ["acknowledge", "handle", "snooze", "dismiss"]},
                    "minutes": {"type": "integer"},
                },
                ["situation_id", "action"],
            ),
            handle_situation,
            changes=True,
        ),
        Tool(
            "remember",
            "Remember a fact or preference a person told you (about_me: it concerns the speaker).",
            _obj({"fact": STR, "about_me": {"type": "boolean"}}, ["fact"]),
            remember,
            changes=True,
        ),
        Tool("recall", "Look up remembered facts and preferences by words.", _obj({"words": STR}), recall),
    )
}

READ_TOOLS = (
    "find_entities",
    "get_states",
    "get_history",
    "list_situations",
    "get_situation",
    "get_journal",
    "get_system_log",
    "get_plan",
    "recall",
)
SETS = {
    "p1": READ_TOOLS[:5],
    "investigate": (*READ_TOOLS, "call_service"),
    "chat": tuple(TOOLS),
}


async def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Run a tool; returns (JSON text, is_error). Errors are returned to the model, never raised."""
    tool = TOOLS.get(name)
    if tool is None:
        return json.dumps({"error": f"unknown tool {name}"}), True
    try:
        result = await tool.handler(ctx, args if isinstance(args, dict) else {})
    except Exception as err:
        return json.dumps({"error": clean(str(err), 300)}), True
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT:
        text = text[:MAX_RESULT] + "…(truncated)"
    is_error = isinstance(result, dict) and "error" in result
    return text, is_error
