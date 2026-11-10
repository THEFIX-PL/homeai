"""AI settings: prompt overrides per mission, who may talk and what chat may do, limits per tier connection."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.homeai.ai.prompts import DATA_RULE, LENGTHS, defaults, system_prompt
from custom_components.homeai.ai.providers.base import AIRequest

from .common import setup_homeai
from .fake_ai import FakeProvider, install, tier
from .home import standard_home


async def test_prompt_override_keeps_the_data_rule(hass: HomeAssistant, hass_ws_client) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.prompt_triage": "Be brief and careful."})
    assert system_prompt(rt, "triage") == f"Be brief and careful.\n\n{DATA_RULE}"
    assert system_prompt(rt, "chat") == defaults()["chat"]
    rt.settings.set("ai.prompt_chat", f"You are {{name}}.\n\n{DATA_RULE}")
    assert system_prompt(rt, "chat").count(DATA_RULE) == 1
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "homeai/ai/prompts"})
    msg = await client.receive_json()
    prompts = {p["mission"]: p for p in msg["result"]["prompts"]}
    assert (
        prompts["triage"]["custom"] == "Be brief and careful." and prompts["triage"]["default"] == defaults()["triage"]
    )
    assert prompts["digest"]["custom"] == ""


async def test_chat_uses_custom_prompt_length_and_tools(hass: HomeAssistant, hass_admin_user) -> None:
    standard_home(hass)
    rt = await setup_homeai(
        hass,
        {"ai.prompt_chat": "You are {name}, terse.", "ai.chat_length": "detailed", "ai.chat_can": "read"},
        subentries=[tier()],
    )
    fake = FakeProvider([{"text": "Fine."}])
    install(rt, "p1", fake)
    reply, _ = await rt.module("ai").chat("How is it?", "c1", hass_admin_user.id)
    assert reply == "Fine."
    request = fake.requests[0]
    assert request.system.startswith("You are HomeAI, terse.") and LENGTHS["detailed"] in request.system
    names = {t.name for t in request.tools}
    assert "get_states" in names and "call_service" not in names and "edit_config" not in names
    rt.settings.set("ai.chat_can", "act", confirmed=True)
    await rt.module("ai").chat("And now?", "c2", hass_admin_user.id)
    names = {t.name for t in fake.requests[-1].tools}
    assert "call_service" in names and "edit_config" not in names


async def test_who_may_talk(hass: HomeAssistant, hass_admin_user, hass_read_only_user) -> None:
    home = standard_home(hass)
    home.person("guest", "Guest", user_id=hass_read_only_user.id)
    home.person("owner", "Owner", user_id=hass_admin_user.id)
    rt = await setup_homeai(
        hass,
        {"ai.chat_who": "residents"},
        overrides={
            "person:person.guest": {"presence.role": "guest"},
            "person:person.owner": {"presence.role": "admin"},
        },
        subentries=[tier()],
    )
    fake = FakeProvider([{"text": "Hello."}])
    install(rt, "p1", fake)
    ai = rt.module("ai")
    reply, _ = await ai.chat("Open the door", "g", hass_read_only_user.id)
    assert reply == "Sorry, I can only talk with the people this home allows." and not fake.requests
    reply, _ = await ai.chat("Hi", "o", hass_admin_user.id)
    assert reply == "Hello."
    reply, _ = await ai.chat("Hi", "anon", None)  # a voice satellite without a user is not a resident
    assert reply.startswith("Sorry")


class CountingProvider(FakeProvider):
    """Remembers how many messages each request carried when it was sent."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lengths: list[int] = []

    async def complete(self, request: AIRequest):
        self.lengths.append(len(request.messages))
        return await super().complete(request)


async def test_shared_threads(hass: HomeAssistant, hass_admin_user, hass_read_only_user) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, subentries=[tier()])
    fake = CountingProvider([{"text": "One."}, {"text": "Two."}, {"text": "Three."}])
    install(rt, "p1", fake)
    ai = rt.module("ai")
    await ai.chat("First", "kitchen", hass_admin_user.id)
    await ai.chat("Second", "kitchen", hass_read_only_user.id)  # another person: a fresh thread
    assert fake.lengths[1] == 1
    rt.settings.set("ai.chat_shared_threads", True)
    await ai.chat("Third", "kitchen", hass_admin_user.id)
    assert fake.lengths[2] == 3  # continues the thread started by someone else


async def test_tier_connection_limits(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(
        hass,
        subentries=[
            tier(priority=1, max_tokens=512, timeout=20, budget_daily=0.001),
            tier(model="claude-sonnet-5-5", priority=2),
        ],
    )
    first, second = FakeProvider([{"text": "a"}], cost=0.002), FakeProvider([{"text": "b"}])
    install(rt, "p1", first, 0)
    install(rt, "p1", second, 1)
    ai = rt.module("ai")
    response = await ai.ask("p1", AIRequest(system="s", messages=[{"role": "user", "content": "x"}], max_tokens=4096))
    assert response.text == "a"
    assert first.requests[0].max_tokens == 512 and first.requests[0].timeout == 20
    # The first connection spent its own budget: the second answers, with the tier's own limits.
    response = await ai.ask("p1", AIRequest(system="s", messages=[{"role": "user", "content": "y"}], max_tokens=4096))
    assert response.text == "b" and len(first.requests) == 1
    assert second.requests[0].max_tokens == 4096 and second.requests[0].timeout == 90
    assert ai.status[ai.tiers["p1"][0].subentry_id] == "budget"
