"""Service handlers. Imported once by `async_register_services`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from ..const import DOMAIN
from ..signals.detectors.external import parse_external
from .services import SERVICES, ServiceDef


async def _who(rt: Any, call: ServiceCall) -> str:
    if call.context.user_id:
        user = await rt.hass.auth.async_get_user(call.context.user_id)
        for p in rt.world.persons.values():
            if p.user_id == call.context.user_id:
                return p.name
        if user:
            return user.name or "?"
    return "automation"


def _module(rt: Any, name: str) -> Any:
    module = rt.module(name)
    if module is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return module


async def report_signal(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    signal = parse_external(dict(call.data), source="service")
    if signal is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="bad_signal")
    expires = (
        dt_util.utcnow() + timedelta(minutes=call.data["expires_minutes"]) if call.data.get("expires_minutes") else None
    )
    hub = _module(rt, "signals")
    hub.external.report(signal, expires)
    hub.evaluate({"external"})
    return {"signal_id": signal.id}


async def clear_signal(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    hub = _module(rt, "signals")
    cleared = hub.external.clear(f"external:service:{call.data['id']}")
    hub.evaluate({"external"})
    return {"cleared": cleared}


def _situation_ids(rt: Any, call: ServiceCall) -> list[str]:
    engine = _module(rt, "situations")
    if call.data.get("situation_id"):
        return [call.data["situation_id"]]
    return [s.id for s in engine.open()]


async def acknowledge(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    engine, who = _module(rt, "situations"), await _who(rt, call)
    done = [s.id for sid in _situation_ids(rt, call) if (s := await engine.acknowledge(sid, who))]
    return {"acknowledged": done}


async def handle(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    engine, who = _module(rt, "situations"), await _who(rt, call)
    done = [s.id for sid in _situation_ids(rt, call) if (s := await engine.handle(sid, who))]
    return {"handled": done}


async def snooze(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    engine, who = _module(rt, "situations"), await _who(rt, call)
    minutes = call.data.get("minutes") or int(rt.settings.get("notify.snooze_minutes"))
    done = [s.id for sid in _situation_ids(rt, call) if (s := await engine.snooze(sid, minutes, who))]
    return {"snoozed": done}


async def dismiss(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    engine, who = _module(rt, "situations"), await _who(rt, call)
    s = await engine.dismiss(call.data["situation_id"], who)
    return {"dismissed": [s.id] if s else []}


async def send_digest(rt: Any, call: ServiceCall) -> ServiceResponse | None:
    sent = await _module(rt, "notify").send_digest()
    return {"sent": sent}


SITUATION = vol.Optional("situation_id")
SERVICES.extend(
    [
        ServiceDef(
            "report_signal",
            report_signal,
            vol.Schema(
                {
                    vol.Required("id"): vol.All(cv.string, vol.Length(min=1, max=100)),
                    vol.Required("title"): vol.All(cv.string, vol.Length(min=1, max=200)),
                    vol.Optional("description", default=""): vol.All(cv.string, vol.Length(max=500)),
                    vol.Optional("severity", default=1): vol.All(vol.Coerce(int), vol.Range(min=0, max=4)),
                    vol.Optional("category", default="info"): vol.In(
                        ["safety", "security", "damage", "system", "energy", "comfort", "maintenance", "info"]
                    ),
                    vol.Optional("need", default="member"): vol.In(["nobody", "member", "admin", "service"]),
                    vol.Optional("entities", default=[]): cv.entity_ids,
                    vol.Optional("group"): cv.string,
                    vol.Optional("expires_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=525600)),
                }
            ),
            SupportsResponse.OPTIONAL,
        ),
        ServiceDef(
            "clear_signal", clear_signal, vol.Schema({vol.Required("id"): cv.string}), SupportsResponse.OPTIONAL
        ),
        ServiceDef("acknowledge", acknowledge, vol.Schema({SITUATION: cv.string}), SupportsResponse.OPTIONAL),
        ServiceDef("handle", handle, vol.Schema({SITUATION: cv.string}), SupportsResponse.OPTIONAL),
        ServiceDef(
            "snooze",
            snooze,
            vol.Schema(
                {SITUATION: cv.string, vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=10080))}
            ),
            SupportsResponse.OPTIONAL,
        ),
        ServiceDef(
            "dismiss", dismiss, vol.Schema({vol.Required("situation_id"): cv.string}), SupportsResponse.OPTIONAL
        ),
        ServiceDef("send_digest", send_digest, vol.Schema({}), SupportsResponse.OPTIONAL),
    ]
)
