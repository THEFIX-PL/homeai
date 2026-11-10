"""Agent loop, P2 investigation, conversations, the conversation entity and the LLM API."""

from __future__ import annotations

import json

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component

from custom_components.homeai.signals.base import Category, Signal

from .common import setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home


def lights(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    @callback
    def handle(call: ServiceCall) -> None:
        calls.append(call)
        ids = call.data["entity_id"]
        for e in [ids] if isinstance(ids, str) else ids:
            hass.states.async_set(e, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("light", "turn_on", handle)
    hass.services.async_register("light", "turn_off", handle)
    return calls


def tool_results(request) -> list[dict]:
    return [
        json.loads(b["content"])
        for m in request.messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("type") == "tool_result"
    ]


async def test_investigation_reads_and_acts_through_policy(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(
        hass,
        {"policy.observation_days": 0, "executor.verify_seconds": 1},
        subentries=[tier(), tier("p2", "claude-opus-5-5")],
    )
    calls = lights(hass)
    install(rt, "p1", FakeProvider([{"severity": 2, "who": "member", "confidence": 0.2, "reason": "?", "steps": []}]))
    p2 = FakeProvider(
        [
            {"tool_calls": [("get_states", {"entity_ids": ["light.ceiling"]})]},
            {
                "tool_calls": [
                    (
                        "call_service",
                        {"service": "light.turn_off", "entity_ids": ["light.ceiling"], "reason": "empty home"},
                    )
                ]
            },
            {
                "severity": 1,
                "who": "nobody",
                "confidence": 0.9,
                "reason": "Lights were left on; turned them off.",
                "steps": [],
            },
        ]
    )
    install(rt, "p2", p2)
    hass.states.async_set("light.ceiling", "on")
    engine = rt.module("situations")
    signal = Signal(
        id="external:test:x",
        detector="external",
        kind="external",
        category=Category.ENERGY,
        severity=2,
        data={"title": "Odd energy use"},
        confidence=0.5,
    )
    engine.on_signals({signal.id: signal})
    await hass.async_block_till_done()
    await engine.process()
    await hass.async_block_till_done()
    [s] = engine.open()
    assert calls and calls[0].context.user_id == rt.system_user_id
    states = tool_results(p2.requests[1])[0]
    assert states[0]["entity_id"] == "light.ceiling" and states[0]["state"] == "on"
    assert tool_results(p2.requests[2])[-1]["status"] == "done"
    assert s.assessment["assessed_by"] == "p2" and s.assessment["actions"][0]["status"] == "done"
    assert p2.requests[0].purpose == "investigate" and {t.name for t in p2.requests[0].tools} >= {
        "call_service",
        "get_history",
    }


async def test_chat_confirmation_flow(hass: HomeAssistant, hass_admin_user) -> None:
    home = standard_home(hass)
    home.person("anna", "Anna", user_id=hass_admin_user.id)
    rt = await setup_homeai(hass, {"policy.person_r2": "confirm", "executor.verify_seconds": 0}, subentries=[tier()])
    switched: list[ServiceCall] = []

    @callback
    def turn_on(call: ServiceCall) -> None:
        switched.append(call)

    hass.services.async_register("switch", "turn_on", turn_on)
    fake = FakeProvider(
        [
            {
                "tool_calls": [
                    ("call_service", {"service": "switch.turn_on", "entity_ids": ["switch.coffee"], "reason": "asked"})
                ]
            },
            {"text": "Should I turn on the coffee plug?"},
            {
                "tool_calls": [
                    (
                        "call_service",
                        {
                            "service": "switch.turn_on",
                            "entity_ids": ["switch.coffee"],
                            "reason": "asked",
                            "confirmed": True,
                        },
                    )
                ]
            },
            {"text": "Done, the coffee plug is on."},
        ]
    )
    install(rt, "p1", fake)
    ai = rt.module("ai")
    reply, actions = await ai.chat("Turn on the coffee machine", "conv1", hass_admin_user.id)
    assert reply == "Should I turn on the coffee plug?" and actions[0]["status"] == "needs_confirmation"
    assert not switched
    reply, actions = await ai.chat("Yes", "conv1", hass_admin_user.id)
    assert reply == "Done, the coffee plug is on."
    assert switched and switched[0].context.user_id == hass_admin_user.id
    # the second turn carried the first turn's history
    second_turn = fake.requests[2].messages
    assert any(m["role"] == "assistant" and m["content"] == "Should I turn on the coffee plug?" for m in second_turn)
    assert "<speaker>Anna</speaker>" in second_turn[-3]["content"] or any("Anna" in str(m) for m in second_turn)
    assert fake.requests[0].system.startswith("You are HomeAI") or "HomeAI" in fake.requests[0].system


async def test_conversation_entity(hass: HomeAssistant, hass_admin_user) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier()])
    install(rt, "p1", FakeProvider([{"text": "All good at home."}]))
    result = await conversation.async_converse(
        hass, "How is the house?", None, Context(user_id=hass_admin_user.id), agent_id="conversation.homeai"
    )
    assert result.response.speech["plain"]["speech"] == "All good at home."


async def test_conversation_without_ai_summarises(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    standard_home(hass)
    await setup_homeai(hass)
    result = await conversation.async_converse(hass, "Status?", None, Context(), agent_id="conversation.homeai")
    assert result.response.speech["plain"]["speech"] == "Everything is fine at home. Nothing needs attention."


async def test_llm_api_for_other_assistants(hass: HomeAssistant, hass_admin_user) -> None:
    standard_home(hass)
    await setup_homeai(hass)
    calls = lights(hass)
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=hass_admin_user.id),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    api = await llm.async_get_api(hass, "homeai", context)
    names = {t.name for t in api.tools}
    assert {"homeai_list_situations", "homeai_call_service"} <= names
    result = await api.async_call_tool(
        llm.ToolInput(
            "homeai_call_service", {"service": "light.turn_on", "entity_ids": ["light.ceiling"], "reason": "asked"}
        )
    )
    assert result.data["status"] in ("done", "unverified")
    assert calls[0].context.user_id == hass_admin_user.id


async def test_tools_respect_privacy_and_errors(hass: HomeAssistant) -> None:
    from custom_components.homeai.ai.privacy import Privacy
    from custom_components.homeai.ai.tools import ToolContext, run_tool

    standard_home(hass)
    rt = await setup_homeai(hass, {"privacy.never_send_entities": ["sensor.bedroom_temperature"]})
    ctx = ToolContext(rt, Privacy(rt))
    text, error = await run_tool(ctx, "get_states", {"entity_ids": ["sensor.bedroom_temperature", "light.ceiling"]})
    data = json.loads(text)
    assert (
        data[0] == {"entity_id": "sensor.bedroom_temperature", "error": "not_available"} and data[1]["state"] == "off"
    )
    text, error = await run_tool(ctx, "find_entities", {"area": "kitchen"})
    assert {e["entity_id"] for e in json.loads(text)} >= {"switch.coffee", "binary_sensor.sink_leak"}
    text, error = await run_tool(ctx, "nope", {})
    assert error
    text, error = await run_tool(ctx, "handle_situation", {"situation_id": "x", "action": "dismiss"})
    assert error  # dismissing is for people
