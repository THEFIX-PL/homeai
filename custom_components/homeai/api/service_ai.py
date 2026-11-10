"""Services `homeai.ask` (talk to HomeAI from automations) and `homeai.run_mission` (run a mission now)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from ..const import DOMAIN
from .service_handlers import _module
from .services import SERVICES, ServiceDef

MISSIONS = ("triage", "investigate", "arbitrate", "digest", "review", "learn")
NEEDS_SITUATION = ("triage", "investigate", "arbitrate")


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)


async def ask(rt: Any, call: ServiceCall) -> ServiceResponse:
    """Ask HomeAI in the caller's account; the answer is the response. Without AI: a summary of open matters."""
    ai = rt.module("ai")
    user_id = call.context.user_id
    conversation = call.data.get("conversation_id") or f"service-{user_id or 'automation'}"
    if ai is None or not (ai.available("p1") or ai.available("p2")):
        engine = rt.module("situations")
        items = [s for s in engine.open() if s.severity >= 1] if engine else []
        text = (
            rt.text("ai|open_summary", count=len(items), titles=[s.title(rt.language) for s in items[:5]])
            if items
            else rt.text("ai|all_quiet")
        )
        return {"reply": text, "actions": [], "ai": False}
    reply, actions = await ai.chat(call.data["text"], conversation, user_id)
    return {
        "reply": reply,
        "actions": [{"what": a.get("what"), "status": a.get("status")} for a in actions],
        "ai": True,
    }


async def run_mission(rt: Any, call: ServiceCall) -> ServiceResponse:
    """Run a mission now. Costs money with AI tiers, so only administrators and automations may call it."""
    if call.context.user_id:
        user = await rt.hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise _error("admin_required")
    mission = call.data["mission"]
    s = None
    if mission in NEEDS_SITUATION:
        s = _module(rt, "situations").get(call.data.get("situation_id") or "")
        if s is None:
            raise _error("situation_unknown")
    if mission == "triage":
        ai = _module(rt, "ai")
        if s.assessment.get("assessed_by") in ("p1", "p2", "p3"):
            s.assessment["assessed_by"] = "code"
        return {"result": await ai.triage(s)}
    if mission == "investigate":
        from ..ai.missions.investigate import investigate

        ai = _module(rt, "ai")
        result = await investigate(ai, s)
        if result is not None:
            rt.module("triage").apply_ai(s, result, "p2")
            await rt.module("situations").reassessed(s)
        return {"result": result}
    if mission == "arbitrate":
        return {"result": await _module(rt, "arbiter").decide_situation(s, "request")}
    if mission == "digest":
        return {"result": await _module(rt, "notify").send_digest()}
    if mission == "review":
        review = await _module(rt, "learning").weekly_review()
        return {"result": {"text": review["text"]}}
    await _module(rt, "learning").nightly()
    return {"result": True}


SERVICES.extend(
    [
        ServiceDef(
            "ask",
            ask,
            vol.Schema(
                {
                    vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=2000)),
                    vol.Optional("conversation_id"): vol.All(cv.string, vol.Length(max=100)),
                }
            ),
            SupportsResponse.ONLY,
        ),
        ServiceDef(
            "run_mission",
            run_mission,
            vol.Schema({vol.Required("mission"): vol.In(MISSIONS), vol.Optional("situation_id"): cv.string}),
            SupportsResponse.OPTIONAL,
        ),
    ]
)
