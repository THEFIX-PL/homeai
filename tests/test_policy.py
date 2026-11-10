"""Risk classes and the policy for people and autonomy."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.homeai.policy import ActionRequest, Risk, Verdict, classify

from .common import setup_homeai
from .home import standard_home


def test_base_classes() -> None:
    assert classify("light", "turn_on", ["light.a"]) == Risk.R1
    assert classify("switch", "turn_on", ["switch.a"]) == Risk.R2
    assert classify("homeassistant", "reload_config_entry", []) == Risk.R3
    assert classify("automation", "turn_off", ["automation.a"]) == Risk.R4
    assert classify("lock", "unlock", ["lock.door"]) == Risk.R5
    assert classify("homeassistant", "restart", []) == Risk.R6
    assert classify("homeassistant", "turn_on", ["light.a", "lock.b"]) == Risk.R5
    assert classify("some_new_domain", "do", []) == Risk.R2  # unknown: careful default
    assert Risk.parse("R3") == Risk.R3 and Risk.parse("auto") is None


async def test_device_class_and_override(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.entity("cover.garage", "closed", device_class="garage", area="Kitchen")
    home.entity("cover.blind", "open", device_class="blind", area="Kitchen")
    rt = await setup_homeai(hass, overrides={"entity:cover.blind": {"policy.risk_override": "R1"}})
    policy = rt.module("policy")
    assert policy.risk(ActionRequest("cover", "open_cover", entity_ids=["cover.garage"])) == Risk.R5
    assert policy.risk(ActionRequest("cover", "open_cover", entity_ids=["cover.blind"])) == Risk.R1


async def test_autonomy_levels_and_observation(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0})
    policy = rt.module("policy")
    light = ActionRequest("light", "turn_off", entity_ids=["light.ceiling"])
    decision = await policy.decide(light)
    assert decision.verdict is Verdict.ALLOW and decision.tell  # act_tell by default
    plug = ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"])
    decision = await policy.decide(plug)
    assert decision.verdict is Verdict.ASK and decision.approver == "residents"
    assert (await policy.decide(ActionRequest("lock", "unlock", entity_ids=[]))).verdict is Verdict.DENY

    rt.settings.set("policy.observation_days", 14, confirmed=True)
    assert policy.observing()
    assert (await policy.decide(light)).verdict is Verdict.OBSERVE
    assert not policy.observing(dt_util.utcnow() + timedelta(days=15))


async def test_system_actions_only_from_playbooks_within_limit(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.repairs_per_day": 2})
    policy = rt.module("policy")
    plain = ActionRequest("homeassistant", "reload_config_entry", {"entry_id": "x"})
    assert (await policy.decide(plain)).verdict is Verdict.ASK
    repair = ActionRequest(
        "homeassistant", "reload_config_entry", {"entry_id": "x"}, actor="repair", playbook="reload_entry"
    )
    assert (await policy.decide(repair)).verdict is Verdict.ALLOW
    policy.count_repair()
    policy.count_repair()
    decision = await policy.decide(repair)
    assert decision.verdict is Verdict.ASK and decision.reason == "repair_limit"


async def test_protective_action_on_labelled_valve(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    label = home.label("HomeAI protective")
    home.entity("valve.main_water", "open", area="Kitchen", labels=("HomeAI protective",))
    home.entity("lock.front", "unlocked", labels=("HomeAI protective",))
    rt = await setup_homeai(hass, {"world.label_protective": label})
    policy = rt.module("policy")
    close = await policy.decide(ActionRequest("valve", "close_valve", entity_ids=["valve.main_water"]))
    assert close.verdict is Verdict.ALLOW and close.protective
    lock = await policy.decide(ActionRequest("lock", "lock", entity_ids=["lock.front"]))
    assert lock.verdict is Verdict.ALLOW  # locking is the safe direction
    unlock = await policy.decide(ActionRequest("lock", "unlock", entity_ids=["lock.front"]))
    assert unlock.verdict is Verdict.DENY


async def test_schedule_up_to_approved_class(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    policy = rt.module("policy")
    req = ActionRequest("switch", "turn_on", entity_ids=["switch.coffee"], actor="schedule", approved_risk=2)
    assert (await policy.decide(req)).verdict is Verdict.ALLOW
    req.approved_risk = 1
    assert (await policy.decide(req)).verdict is Verdict.ASK


async def test_person_requests(hass: HomeAssistant, hass_admin_user, hass_read_only_user) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.person_r2": "confirm"})
    policy = rt.module("policy")

    def req(domain, service, user, **kw):
        return ActionRequest(domain, service, actor="person", user_id=user.id, **kw)

    assert (await policy.decide(req("light", "turn_on", hass_read_only_user))).verdict is Verdict.ALLOW
    assert (await policy.decide(req("switch", "turn_on", hass_read_only_user))).verdict is Verdict.CONFIRM
    assert (await policy.decide(req("switch", "turn_on", hass_read_only_user, confirmed=True))).verdict is Verdict.ALLOW
    reload_ = await policy.decide(req("homeassistant", "reload_config_entry", hass_read_only_user))
    assert reload_.verdict is Verdict.ASK and reload_.approver == "admins"
    assert (await policy.decide(req("homeassistant", "reload_config_entry", hass_admin_user))).verdict is Verdict.ALLOW
    assert (await policy.decide(req("lock", "unlock", hass_read_only_user))).verdict is Verdict.CONFIRM
    assert (await policy.decide(req("homeassistant", "restart", hass_read_only_user))).verdict is Verdict.DENY
    assert (await policy.decide(req("homeassistant", "restart", hass_admin_user))).verdict is Verdict.CONFIRM
