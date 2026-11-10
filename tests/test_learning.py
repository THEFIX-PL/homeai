"""Learning: norms and anomalies, habits as proposals, feedback, weekly review and memory."""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from custom_components.homeai.learning.baselines import hour_of_week, summarise
from custom_components.homeai.learning.habits import find_habits
from custom_components.homeai.policy import ActionRequest, Verdict

from .common import setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home


def test_summarise_hour_of_week() -> None:
    base = datetime(2026, 10, 5, 12, 0, tzinfo=dt_util.get_default_time_zone())  # a Monday noon, local
    rows = [{"start": (base + timedelta(weeks=w)).timestamp(), "mean": 21.0 + w * 0.1} for w in range(4)]
    summary = summarise(rows, min_samples=4)
    bucket = summary["buckets"][hour_of_week(base.timestamp())]
    assert abs(bucket[0] - 21.15) < 0.01 and bucket[2] == 4
    assert summarise(rows, min_samples=10) is None


async def test_anomaly_signal_from_norm(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"learning.anomaly_minutes": 10})
    learning = rt.module("learning")
    learning.baselines.norms["sensor.bedroom_temperature"] = {"buckets": [[21.0, 0.5, 4.0]] * 168}
    hub = rt.module("signals")
    home.set("sensor.bedroom_temperature", "21.4")
    assert not [s for s in hub.evaluate().values() if s and s.kind == "anomaly"]
    home.set("sensor.bedroom_temperature", "28")
    freezer.tick(timedelta(minutes=11))
    [signal] = [s for s in hub.evaluate().values() if s and s.kind == "anomaly"]
    assert signal.confidence == 0.6 and signal.data["usual"].startswith("21.0")


async def test_norms_need_the_recorder(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    assert await rt.module("learning").baselines.refresh() == 0


def _changes(entity_id: str, hour: int, minute: int, days: int, state: str = "on") -> list[tuple[datetime, str]]:
    now = dt_util.now()
    out = []
    for d in range(days):
        day = now - timedelta(days=d + 1)
        if day.weekday() < 5:
            out.append((day.replace(hour=hour, minute=minute + (d % 3), second=0, microsecond=0), state))
    return out


def test_find_habits() -> None:
    found = find_habits({"light.ceiling": _changes("light.ceiling", 6, 40, 21)}, days=21, min_days=8, window=20)
    assert found and found[0]["service"] == "light.turn_on" and found[0]["kind"] == "workday"
    assert found[0]["time"].startswith("06:4")
    assert not find_habits({"light.ceiling": _changes("light.ceiling", 6, 40, 5)}, days=21, min_days=8, window=20)


async def test_habit_proposal_needs_approval(hass: HomeAssistant, hass_admin_user, hass_ws_client) -> None:
    standard_home(hass)
    hass.services.async_register("light", "turn_on", callback(lambda c: None))
    rt = await setup_homeai(hass)
    learning = rt.module("learning")
    [proposal] = await learning.detect_habits({"light.ceiling": _changes("light.ceiling", 6, 40, 21)})
    assert proposal["status"] == "pending" and not rt.module("scheduler").entries
    assert await learning.detect_habits({"light.ceiling": _changes("light.ceiling", 6, 40, 21)}) == []  # no duplicates
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/learning/status"})
    msg = await client.receive_json()
    assert msg["result"]["proposals"][0]["id"] == proposal["id"]
    await client.send_json_auto_id({"type": "homeai/learning/approve", "proposal_id": proposal["id"]})
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["status"] == "approved"
    [entry] = rt.module("scheduler").entries.values()
    assert (
        entry["when"]["days"] == [0, 1, 2, 3, 4] and entry["skip_when_away"] and entry["author"] == hass_admin_user.id
    )


async def test_rejected_habit_is_not_proposed_again(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    learning = rt.module("learning")
    [proposal] = await learning.detect_habits({"light.ceiling": _changes("light.ceiling", 6, 40, 21)})
    assert learning.reject(proposal["id"])
    del learning.proposals[proposal["id"]]
    assert await learning.detect_habits({"light.ceiling": _changes("light.ceiling", 6, 40, 21)}) == []


async def test_undo_and_refusal_teach_the_policy(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "learning.undo_limit": 2})
    learning, policy = rt.module("learning"), rt.module("policy")
    request = ActionRequest("light", "turn_off", entity_ids=["light.ceiling"])
    assert (await policy.decide(request)).verdict is Verdict.ALLOW
    record = {"request": request.as_dict()}
    learning.feedback("undo", record)
    learning.feedback("undo", record)
    assert (await policy.decide(request)).verdict is Verdict.ASK
    plug = ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"])
    learning.feedback("deny", {"request": plug.as_dict()})
    result = await rt.module("executor").execute(plug)
    assert result.status == "denied" and result.message == "recently_refused"
    assert not rt.module("approvals").pending()


async def test_weekly_review(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"learning.review_push": False}, subentries=[tier()])
    install(rt, "p1", FakeProvider([{"text": "A calm week."}]))
    learning = rt.module("learning")
    learning.feedback_counts["light.turn_off:light.ceiling"] = {"approve": 6}
    review = await learning.weekly_review()
    assert review["text"] == "A calm week."
    assert review["facts"]["raise_autonomy"] == ["light.turn_off:light.ceiling"]
    assert "homeai_weekly_review" in persistent_notification._async_get_or_create_notifications(hass)


async def test_review_without_ai_is_plain(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"learning.review_push": False})
    review = await rt.module("learning").weekly_review()
    assert review["text"].startswith("Situations resolved this week: 0")


async def test_memory_and_tools(hass: HomeAssistant, hass_admin_user) -> None:
    import json

    from custom_components.homeai.ai.privacy import Privacy
    from custom_components.homeai.ai.tools import ToolContext, run_tool

    home = standard_home(hass)
    home.person("anna", "Anna", user_id=hass_admin_user.id)
    rt = await setup_homeai(hass, subentries=[tier()])
    memory = rt.module("memory")
    ctx = ToolContext(rt, Privacy(rt), actor="person", user_id=hass_admin_user.id)
    text, _ = await run_tool(ctx, "remember", {"fact": "Anna prefers 20 °C in the bedroom at night", "about_me": True})
    assert json.loads(text).get("approved") is True, text
    [fact] = memory.facts.values()
    assert fact["scope"] == "person:person.anna"
    memory.add("Anna prefers 20 °C in the bedroom at night", scope="person:person.anna")
    assert len(memory.facts) == 1  # the same fact refreshes
    learned = memory.add("The dog is walked at 7", source="learning", confidence=0.6)
    assert not learned["approved"] and memory.search("dog") == []
    memory.approve(learned["id"])
    assert memory.search("dog")[0]["id"] == learned["id"]
    text, _ = await run_tool(ctx, "recall", {"words": "bedroom"})
    assert "20 °C" in text

    fake = FakeProvider([{"text": "Noted."}])
    install(rt, "p1", fake)
    await rt.module("ai").chat("What temperature do I like in the bedroom?", "c1", hass_admin_user.id)
    user_turn = next(m for m in fake.requests[0].messages if m["role"] == "user")
    assert "<facts>" in user_turn["content"] and "20 °C" in user_turn["content"]
