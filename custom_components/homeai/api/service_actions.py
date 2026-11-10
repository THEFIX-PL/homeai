"""Services for actions, approvals, the plan and presence exceptions."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from ..const import DOMAIN
from ..schedule.presence import KINDS as PRESENCE_KINDS
from ..schedule.scheduler import PlanError
from .service_handlers import _module
from .services import SERVICES, ServiceDef


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)


async def approve(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    if not call.context.user_id:
        raise _error("person_required")
    item = await _module(rt, "approvals").approve(call.data["approval_id"], call.context.user_id)
    if item is None:
        raise _error("approval_unavailable")
    return {"status": item["status"], "result": item.get("result")}


async def deny(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    if not call.context.user_id:
        raise _error("person_required")
    item = await _module(rt, "approvals").deny(call.data["approval_id"], call.context.user_id)
    if item is None:
        raise _error("approval_unavailable")
    return {"status": item["status"]}


async def undo(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    result = await _module(rt, "executor").undo(call.data["action_id"], call.context.user_id)
    return result.as_dict()


def _when(data: dict[str, Any]) -> dict[str, Any]:
    when: dict[str, Any] = {"kind": data["kind"]}
    for key in ("time", "date", "days", "event", "offset"):
        if key in data:
            value = data[key]
            when[key] = value.isoformat() if isinstance(value, date) else value
    if isinstance(when.get("time"), str) and len(when["time"]) > 5:
        when["time"] = when["time"][:5]
    return when


async def plan_add(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    data = dict(call.data)
    raw: dict[str, Any] = {
        "title": data.get("title", ""),
        "when": _when(data),
        "skip_when_away": data.get("skip_when_away", False),
    }
    if data.get("reminder"):
        raw["reminder"] = data["reminder"]
        raw["to"] = data.get("to", "home_or_all")
    elif data.get("service"):
        raw["action"] = {
            "service": data["service"],
            "entity_ids": data.get("entity_id", []),
            "data": data.get("data", {}),
        }
    else:
        raise _error("plan_invalid", reason="service or reminder")
    try:
        entry = await _module(rt, "scheduler").save(raw, call.context.user_id)
    except PlanError as err:
        raise _error("plan_invalid", reason=str(err)) from err
    return {"entry_id": entry["id"], "approved_risk": entry["approved_risk"]}


async def plan_remove(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    try:
        removed = await _module(rt, "scheduler").remove(call.data["entry_id"], call.context.user_id)
    except PlanError as err:
        raise _error("plan_invalid", reason=str(err)) from err
    return {"removed": removed}


async def plan_skip(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    return {"skipped": _module(rt, "scheduler").skip(call.data["entry_id"], call.data["date"])}


async def presence_add(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    try:
        item = _module(rt, "presence_exceptions").save(
            {k: call.data.get(k) for k in ("kind", "person", "start", "end", "note")}, author=call.context.user_id
        )
    except (ValueError, KeyError) as err:
        raise _error("presence_invalid", reason=str(err)) from err
    return {"exception_id": item["id"]}


async def presence_remove(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    return {"removed": _module(rt, "presence_exceptions").remove(call.data["exception_id"])}


DAYS = vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))])
SERVICES.extend(
    [
        ServiceDef("approve", approve, vol.Schema({vol.Required("approval_id"): cv.string}), SupportsResponse.OPTIONAL),
        ServiceDef("deny", deny, vol.Schema({vol.Required("approval_id"): cv.string}), SupportsResponse.OPTIONAL),
        ServiceDef("undo", undo, vol.Schema({vol.Required("action_id"): cv.string}), SupportsResponse.OPTIONAL),
        ServiceDef(
            "plan_add",
            plan_add,
            vol.Schema(
                {
                    vol.Optional("title", default=""): vol.All(cv.string, vol.Length(max=200)),
                    vol.Optional("service"): cv.service,
                    vol.Optional("entity_id", default=[]): cv.entity_ids,
                    vol.Optional("data", default={}): dict,
                    vol.Optional("reminder"): vol.All(cv.string, vol.Length(min=1, max=500)),
                    vol.Optional("to", default="home_or_all"): vol.In(["all", "home", "home_or_all", "admins"]),
                    vol.Required("kind"): vol.In(["once", "daily", "weekly", "sun"]),
                    vol.Optional("time"): cv.string,
                    vol.Optional("date"): cv.date,
                    vol.Optional("days"): DAYS,
                    vol.Optional("event"): vol.In(["sunrise", "sunset", "dawn", "dusk", "solar_noon"]),
                    vol.Optional("offset"): vol.All(vol.Coerce(int), vol.Range(min=-720, max=720)),
                    vol.Optional("skip_when_away", default=False): cv.boolean,
                }
            ),
            SupportsResponse.OPTIONAL,
        ),
        ServiceDef(
            "plan_remove", plan_remove, vol.Schema({vol.Required("entry_id"): cv.string}), SupportsResponse.OPTIONAL
        ),
        ServiceDef(
            "plan_skip",
            plan_skip,
            vol.Schema({vol.Required("entry_id"): cv.string, vol.Required("date"): cv.date}),
            SupportsResponse.OPTIONAL,
        ),
        ServiceDef(
            "presence_add",
            presence_add,
            vol.Schema(
                {
                    vol.Required("kind"): vol.In(list(PRESENCE_KINDS)),
                    vol.Optional("person"): cv.entity_id,
                    vol.Required("start"): vol.Any(cv.datetime, cv.date),
                    vol.Required("end"): vol.Any(cv.datetime, cv.date),
                    vol.Optional("note", default=""): vol.All(cv.string, vol.Length(max=300)),
                }
            ),
            SupportsResponse.OPTIONAL,
        ),
        ServiceDef(
            "presence_remove",
            presence_remove,
            vol.Schema({vol.Required("exception_id"): cv.string}),
            SupportsResponse.OPTIONAL,
        ),
    ]
)
