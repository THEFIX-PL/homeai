"""Interfaces from the plan: autonomy slider, configuration entities, next plan change, ask, run_mission, Repairs."""

from __future__ import annotations

from homeassistant.core import Context, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest

from custom_components.homeai.const import DOMAIN
from custom_components.homeai.policy import ActionRequest, Risk, Verdict
from custom_components.homeai.policy.engine import slide
from custom_components.homeai.signals.base import Category, Signal

from .common import setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home


def test_slider_over_levels() -> None:
    assert slide("act_tell", Risk.R1, "balanced") == "act_tell"
    assert slide("act_tell", Risk.R1, "observe") == "observe"
    assert slide("act", Risk.R3, "observe") == "observe"
    assert slide("act_tell", Risk.R1, "cautious") == "propose"
    assert slide("act", Risk.R3, "cautious") == "act"  # repairs still run
    assert slide("propose", Risk.R2, "bold") == "act_tell"
    assert slide("propose", Risk.R4, "bold") == "propose"  # configuration never automatic
    assert slide("never", Risk.R1, "bold") == "never"


async def test_autonomy_select_needs_admin(hass: HomeAssistant, hass_admin_user, hass_read_only_user) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0})
    state = hass.states.get("select.homeai_autonomy")
    assert state.state == "balanced" and "bold" in state.attributes["options"]
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.homeai_autonomy", "option": "bold"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.homeai_autonomy", "option": "observe"},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert rt.settings.get("policy.slider") == "observe"
    decision = await rt.module("policy").decide(ActionRequest("light", "turn_off", entity_ids=["light.ceiling"]))
    assert decision.verdict is Verdict.OBSERVE


async def test_configuration_entities(hass: HomeAssistant, hass_admin_user) -> None:
    # the admin fixture first, so the member created below is not the owner
    standard_home(hass)
    rt = await setup_homeai(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.homeai_ai"}, blocking=True)
    assert rt.settings.get("ai.enabled") is False
    # vacation mode is not admin-only: any resident may switch it
    member = await hass.auth.async_create_user("Member", group_ids=["system-users"])
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.homeai_vacation"}, blocking=True, context=Context(user_id=member.id)
    )
    assert rt.presence.vacation()
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.homeai_ai_budget_monthly", "value": 25}, blocking=True
    )
    assert rt.settings.get("ai.budget_monthly") == 25
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": "number.homeai_ai_budget_monthly", "value": 99},
            blocking=True,
            context=Context(user_id=member.id),
        )


async def test_vacation_raises_security(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"presence.vacation_mode": True})
    engine = rt.module("situations")
    engine.on_signals(
        {"door": Signal(id="door", detector="t", kind="opening_away", category=Category.SECURITY, severity=2)}
    )
    await hass.async_block_till_done()
    await engine.process()
    [s] = engine.open()
    assert s.severity == 3 and "everyone_away" in s.assessment["reasons"]


async def test_next_plan_change_sensor(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    assert hass.states.get("sensor.homeai_next_plan_change").state == "unknown"
    at = dt_util.as_local(dt_util.utcnow()).replace(second=0, microsecond=0)
    when = (at.hour + 2) % 24
    await rt.module("scheduler").save(
        {"reminder": "Water the plants", "when": {"kind": "daily", "time": f"{when:02d}:00"}}, None
    )
    await hass.async_block_till_done()
    state = hass.states.get("sensor.homeai_next_plan_change")
    assert state.state not in ("unknown", "unavailable") and state.attributes["title"] == "Water the plants"


async def test_ask_service(hass: HomeAssistant, hass_admin_user) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier()])
    install(rt, "p1", FakeProvider([{"text": "All quiet."}]))
    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"text": "How is the house?"},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert result == {"reply": "All quiet.", "actions": [], "ai": True}


async def test_ask_without_ai(hass: HomeAssistant) -> None:
    standard_home(hass)
    await setup_homeai(hass)
    result = await hass.services.async_call(DOMAIN, "ask", {"text": "Status?"}, blocking=True, return_response=True)
    assert result["ai"] is False and result["reply"] == "Everything is fine at home. Nothing needs attention."


async def test_run_mission(hass: HomeAssistant, hass_read_only_user) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.triage_enabled": False}, subentries=[tier()])
    install(
        rt, "p1", FakeProvider([{"severity": 1, "who": "member", "confidence": 0.9, "reason": "Fine.", "steps": []}])
    )
    engine = rt.module("situations")
    engine.on_signals(
        {
            "x": Signal(
                id="x", detector="t", kind="external", category=Category.SYSTEM, severity=2, data={"title": "Odd"}
            )
        }
    )
    await hass.async_block_till_done()
    await engine.process()
    [s] = engine.open()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "run_mission",
            {"mission": "triage", "situation_id": s.id},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "run_mission", {"mission": "triage", "situation_id": "nope"}, blocking=True, return_response=True
        )
    result = await hass.services.async_call(
        DOMAIN, "run_mission", {"mission": "triage", "situation_id": s.id}, blocking=True, return_response=True
    )
    assert result["result"]["severity"] == 1 and s.assessment["assessed_by"] == "p1"
    review = await hass.services.async_call(
        DOMAIN, "run_mission", {"mission": "review"}, blocking=True, return_response=True
    )
    assert review["result"]["text"]


async def test_repairs_hints(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    checks = rt.module("checks")
    assert checks.run() == {"no_phones"}  # people and rooms exist, phones do not
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "no_phones") is not None
    calls: list[ServiceCall] = []
    hass.services.async_register("notify", "mobile_app_anna", callback(lambda c: calls.append(c)))  # noqa: PLW0108
    rt.settings.set("notify.targets", ["notify.mobile_app_anna"], skey="person:person.anna", confirmed=True)
    assert checks.run() == set()
    assert registry.async_get_issue(DOMAIN, "no_phones") is None
    # and the situation engine does not turn HomeAI's own hints into situations
    hub = rt.module("signals")
    checks.problems = lambda: {"no_residents"}  # type: ignore[method-assign]
    checks.run()
    hub.evaluate()
    assert not any(s.kind == "repairs_issues" for s in hub.signals.values())
