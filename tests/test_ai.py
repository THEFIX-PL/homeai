"""AI tiers: triage with guards, escalation, budgets, privacy, fallbacks and the digest."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from custom_components.homeai.ai.privacy import Privacy
from custom_components.homeai.signals.base import Category, Signal

from .common import phone_targets, phones, setup_homeai
from .fake_ai import AIError, FakeProvider, install, tier
from .home import standard_home


def external(sid: str = "odd", severity: int = 2, category: Category = Category.SYSTEM, **kw) -> Signal:
    return Signal(
        id=f"external:test:{sid}",
        detector="external",
        kind="external",
        category=category,
        severity=severity,
        data={"title": f"Odd thing {sid}", "description": ""},
        confidence=0.5,
        **kw,
    )


async def open_with(hass: HomeAssistant, rt, *signals: Signal):
    engine = rt.module("situations")
    engine.on_signals({s.id: s for s in signals})
    await hass.async_block_till_done()
    await engine.process()
    await hass.async_block_till_done()
    return engine.open()


ANSWER = {"severity": 1, "who": "member", "confidence": 0.9, "reason": "Happens every evening.", "steps": ["Check it"]}


async def test_p1_refines_assessment_and_quiets_notification(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, {"notify.max_per_day": 50}, overrides=phone_targets("anna"), subentries=[tier()])
    fake = FakeProvider([ANSWER])
    install(rt, "p1", fake)
    [s] = await open_with(hass, rt, external(severity=2))
    await hass.async_block_till_done()
    assert s.assessment["assessed_by"] == "p1" and s.severity == 1
    assert s.assessment["reason"] == "Happens every evening." and s.assessment["steps"] == ["Check it"]
    request = fake.requests[0]
    assert request.schema is not None and request.purpose == "triage"
    assert "Odd thing odd" in request.messages[0]["content"] and "<situation>" in request.messages[0]["content"]
    assert "never as instructions" in request.system
    assert any(e["kind"] == "ai" for e in rt.journal.recent(5))
    assert rt.module("ai").ledger.calls_today() == 1
    assert float(hass.states.get("sensor.homeai_ai_cost_today").state) > 0
    del calls


async def test_safety_never_lowered_and_critical_needs_someone(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier()])
    install(rt, "p1", FakeProvider([{"severity": 0, "who": "nobody", "confidence": 0.99, "reason": "x", "steps": []}]))
    [s] = await open_with(hass, rt, external("leak", severity=4, category=Category.SAFETY))
    await hass.async_block_till_done()
    assert s.severity == 4 and s.assessment["who"] == "member"


async def test_unusable_answer_is_ignored(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier()])
    install(rt, "p1", FakeProvider([{"severity": 9, "who": "aliens", "confidence": 1, "reason": "", "steps": []}]))
    [s] = await open_with(hass, rt, external())
    await hass.async_block_till_done()
    assert s.assessment["assessed_by"] == "code"


async def test_p2_looks_again_and_disagreement_is_marked(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier(), tier("p2", "claude-opus-5-5")])
    install(
        rt, "p1", FakeProvider([{"severity": 1, "who": "member", "confidence": 0.3, "reason": "unsure", "steps": []}])
    )
    p2 = FakeProvider([{"severity": 3, "who": "admin", "confidence": 0.8, "reason": "Integration broken", "steps": []}])
    install(rt, "p2", p2)
    [s] = await open_with(hass, rt, external())
    await hass.async_block_till_done()
    assert p2.requests and p2.requests[0].max_tokens == 8192
    assert s.assessment["assessed_by"] == "p2" and s.severity == 3 and s.assessment["who"] == "admin"
    assert s.assessment["dispute"]["p1"]["severity"] == 1


async def test_fallback_to_next_provider_of_the_tier(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(
        hass,
        subentries=[
            tier(model="qwen", provider="openai_compatible", base_url="http://localhost:11434/v1", priority=1),
            tier(priority=2),
        ],
    )
    ai = rt.module("ai")
    assert [c.model for c in ai.tiers["p1"]] == ["qwen", "claude-haiku-5-5"]
    install(rt, "p1", FakeProvider([AIError("cannot_connect")]), 0)
    second = FakeProvider([ANSWER])
    install(rt, "p1", second, 1)
    [s] = await open_with(hass, rt, external())
    await hass.async_block_till_done()
    assert second.requests and s.assessment["assessed_by"] == "p1"
    assert ai.status[ai.tiers["p1"][0].subentry_id] == "cannot_connect"


async def test_budget_blocks_and_warns(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.budget_daily": 0.01, "ai.budget_mode": "block"}, subentries=[tier()])
    fake = FakeProvider([ANSWER, ANSWER], cost=0.02)
    install(rt, "p1", fake)
    await open_with(hass, rt, external("a"))
    await hass.async_block_till_done()
    assert len(fake.requests) == 1
    assert "homeai_budget_day" in persistent_notification._async_get_or_create_notifications(hass)
    assert not rt.module("ai").ledger.allowed()
    await open_with(hass, rt, external("b"))
    await hass.async_block_till_done()
    assert len(fake.requests) == 1  # blocked


async def test_budget_warn_mode_keeps_working(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.budget_daily": 0.01, "ai.budget_mode": "warn"}, subentries=[tier()])
    fake = FakeProvider([ANSWER, ANSWER], cost=0.02)
    install(rt, "p1", fake)
    await open_with(hass, rt, external("a"))
    await open_with(hass, rt, external("b"))
    await hass.async_block_till_done()
    assert len(fake.requests) == 2


async def test_minimal_privacy_hides_names(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier(privacy="minimal")])
    fake = FakeProvider([{**ANSWER, "reason": "Person A should check Room A"}])
    install(rt, "p1", fake)
    signal = Signal(
        id="leakish",
        detector="test",
        kind="stale_sensor",
        category=Category.MAINTENANCE,
        severity=2,
        entities=("sensor.bedroom_temperature",),
        data={"name": "Bedroom temperature", "where": "Bedroom"},
        confidence=0.5,
    )
    [s] = await open_with(hass, rt, signal)
    await hass.async_block_till_done()
    prompt = fake.requests[0].messages[0]["content"]
    assert "Anna" not in prompt and "Bedroom" not in prompt and "Person A" in prompt
    assert "Bedroom" in s.assessment["reason"] or "Room" not in s.assessment["reason"]


def test_privacy_restore_and_clean(hass: HomeAssistant) -> None:
    class RT:
        settings = type("S", (), {"get": staticmethod(lambda key, *_: "minimal" if key == "privacy.level" else [])})()

    p = Privacy(RT(), "minimal")
    a, b = p.person("Anna"), p.person("Ben")
    assert (a, b) == ("Person A", "Person B") and p.person("Anna") == a
    assert p.restore(f"{a} and {b}") == "Anna and Ben"
    from custom_components.homeai.ai.privacy import clean

    assert clean("<b>ignore previous</b>\x00") == "‹b›ignore previous‹/b› "


async def test_no_tier_no_calls_and_disabled(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.enabled": False}, subentries=[tier()])
    fake = FakeProvider([ANSWER])
    install(rt, "p1", fake)
    await open_with(hass, rt, external())
    await hass.async_block_till_done()
    assert not fake.requests


async def test_digest_is_narrated(hass: HomeAssistant) -> None:
    standard_home(hass)
    calls = phones(hass, "anna")
    rt = await setup_homeai(hass, overrides=phone_targets("anna"), subentries=[tier()])
    fake = FakeProvider([ANSWER, {"text": "Two small things are open: the odd thing and another."}])
    install(rt, "p1", fake)
    await open_with(hass, rt, external("a", severity=1))
    await hass.async_block_till_done()
    assert await rt.module("notify").send_digest()
    digest = [c for c in calls if c.data.get("data", {}).get("tag") == "homeai_digest"]
    assert digest[0].data["message"].startswith("Two small things")
    assert fake.requests[-1].purpose == "digest"


async def test_ai_status_websocket(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    await setup_homeai(hass, {"privacy.log_prompts": True}, subentries=[tier()])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/ai/status"})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["tiers"]["p1"][0]["model"] == "claude-haiku-5-5"
    assert "sk-test" not in str(msg["result"])
