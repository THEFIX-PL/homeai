"""The arbiter: disputes, risky requests while nobody is home, limits on what it may approve."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.setup import async_setup_component

from custom_components.homeai.policy import ActionRequest
from custom_components.homeai.signals.base import Category, Signal

from .common import setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home

TIERS = [tier(), tier("p2", "claude-opus-5-5"), tier("p3", "claude-fable-5-1")]


def decision(kind: str = "approve", severity: int = 2, who: str = "member", confidence: float = 0.9) -> dict:
    return {
        "decision": kind,
        "severity": severity,
        "who": who,
        "confidence": confidence,
        "reason": "The evidence points to a stuck sensor.",
        "conditions": ["sensor reports again"],
    }


async def test_dispute_is_settled(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=TIERS)
    install(
        rt, "p1", FakeProvider([{"severity": 1, "who": "member", "confidence": 0.3, "reason": "minor", "steps": []}])
    )
    install(
        rt, "p2", FakeProvider([{"severity": 3, "who": "admin", "confidence": 0.7, "reason": "serious", "steps": []}])
    )
    p3 = FakeProvider([decision("reject", 2, "member")])
    install(rt, "p3", p3)
    engine = rt.module("situations")
    signal = Signal(
        id="external:t:x",
        detector="external",
        kind="external",
        category=Category.SYSTEM,
        severity=2,
        data={"title": "Odd"},
        confidence=0.4,
    )
    engine.on_signals({signal.id: signal})
    await hass.async_block_till_done()
    await engine.process()
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    [s] = engine.open()
    assert p3.requests and p3.requests[0].purpose == "arbiter_dispute" and p3.requests[0].effort == "high"
    assert "<assessments>" in p3.requests[0].messages[0]["content"]
    assert s.assessment["assessed_by"] == "p3" and s.severity == 2 and s.assessment["arbiter"]["decision"] == "reject"
    arbiter = rt.module("arbiter")
    assert arbiter.dossiers[-1]["case"] == "dispute"
    assert any(e["kind"] == "decision" for e in rt.journal.recent(10))


async def test_risky_request_while_away_reviewed_but_not_approved_by_default(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.set("person.anna", "not_home")
    rt = await setup_homeai(hass, {"policy.observation_days": 0}, subentries=TIERS)
    p3 = FakeProvider([decision()])
    install(rt, "p3", p3)
    result = await rt.module("executor").execute(ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"]))
    await hass.async_block_till_done()
    item = rt.module("approvals").items[result.approval_id]
    assert p3.requests and item["status"] == "pending" and item["arbiter"]["decision"] == "approve"


async def test_arbiter_may_approve_up_to_r3_when_allowed(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.set("person.anna", "not_home")
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "ai.arbiter_can_approve": True}, subentries=TIERS)
    switched: list[ServiceCall] = []

    @callback
    def turn_off(call: ServiceCall) -> None:
        switched.append(call)

    hass.services.async_register("switch", "turn_off", turn_off)
    install(rt, "p3", FakeProvider([decision()]))
    result = await rt.module("executor").execute(ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"]))
    await hass.async_block_till_done()
    item = rt.module("approvals").items[result.approval_id]
    assert item["status"] == "approved" and item["decided_by"] == "HomeAI arbiter"
    assert switched and switched[0].context.user_id == rt.system_user_id


async def test_arbiter_never_approves_configuration(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.arbiter_can_approve": True}, subentries=TIERS)
    p3 = FakeProvider([decision(confidence=1.0)])
    install(rt, "p3", p3)
    result = await rt.module("executor").execute(
        ActionRequest("config", "automation_save", {"id": "x", "config": {"alias": "x"}})
    )
    await hass.async_block_till_done()
    item = rt.module("approvals").items[result.approval_id]
    assert p3.requests and p3.requests[0].effort == "high"
    assert item["status"] == "pending" and item["arbiter"]["decision"] == "approve"


async def test_low_confidence_or_limit_stops_the_arbiter(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.set("person.anna", "not_home")
    rt = await setup_homeai(
        hass, {"policy.observation_days": 0, "ai.arbiter_can_approve": True, "ai.arbiter_per_day": 1}, subentries=TIERS
    )
    p3 = FakeProvider([decision(confidence=0.5), decision()])
    install(rt, "p3", p3)
    executor = rt.module("executor")
    first = await executor.execute(ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"]))
    await hass.async_block_till_done()
    assert rt.module("approvals").items[first.approval_id]["status"] == "pending"  # not sure enough
    hass.states.async_set("switch.coffee2", "on")
    second = await executor.execute(ActionRequest("switch", "turn_on", entity_ids=["switch.coffee"]))
    await hass.async_block_till_done()
    assert len(p3.requests) == 1  # daily limit
    assert rt.module("approvals").items[second.approval_id]["status"] == "pending"


async def test_arbitrate_websocket(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=TIERS)
    install(rt, "p3", FakeProvider([decision("escalate_human", 3, "admin")]))
    engine = rt.module("situations")
    signal = Signal(id="s1", detector="t", kind="external", category=Category.SYSTEM, severity=2, data={"title": "Odd"})
    engine.on_signals({"s1": signal})
    await hass.async_block_till_done()
    await engine.process()
    [s] = engine.open()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/ai/arbitrate", "situation_id": s.id})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["decision"]["decision"] == "escalate_human"
    assert s.assessment["who"] == "admin"
    await client.send_json_auto_id({"type": "homeai/ai/dossiers"})
    msg = await client.receive_json()
    assert msg["result"]["dossiers"][0]["case"] == "request"
