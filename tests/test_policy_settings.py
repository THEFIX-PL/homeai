"""Policy, repair and plan settings: actor × class matrix, risk by action and label, playbooks, who may plan."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.homeai.policy import ActionRequest, Risk, Verdict, classify
from custom_components.homeai.schedule.scheduler import PlanError
from custom_components.homeai.settings import SettingError, build_registry

from .common import setup_homeai
from .home import standard_home
from .test_repair import failing_integration, open_with


async def test_actor_matrix(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0, "policy.actor_ai_r1": "propose"})
    policy = rt.module("policy")
    light = {"domain": "light", "service": "turn_off", "entity_ids": ["light.ceiling"]}
    assert (await policy.decide(ActionRequest(**light, actor="homeai"))).verdict is Verdict.ALLOW
    decision = await policy.decide(ActionRequest(**light, actor="ai"))
    assert decision.verdict is Verdict.ASK and decision.approver == "residents"
    # The slider still caps an actor's own level.
    rt.settings.set("policy.actor_ai_r1", "act", confirmed=True)
    rt.settings.set("policy.slider", "observe", confirmed=True)
    assert (await policy.decide(ActionRequest(**light, actor="ai"))).verdict is Verdict.OBSERVE


async def test_matrix_for_the_plan(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass, {"policy.observation_days": 0})
    policy = rt.module("policy")
    plug = ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"], actor="schedule", approved_risk=2)
    assert (await policy.decide(plug)).verdict is Verdict.ALLOW  # inherit: the author's approval is enough
    rt.settings.set("policy.actor_schedule_r2", "observe", confirmed=True)
    assert (await policy.decide(plug)).verdict is Verdict.OBSERVE
    above = ActionRequest("switch", "turn_off", entity_ids=["switch.coffee"], actor="schedule", approved_risk=1)
    assert (await policy.decide(above)).verdict is Verdict.ASK


async def test_risk_by_service_and_label(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    home.entity("light.kids", "off", area="Bedroom", labels=("Kids room",))
    kids = home.label("Kids room")
    rt = await setup_homeai(
        hass,
        {
            "policy.risk_by_service": {"light": "R3", "light.turn_off": "R2", "homeassistant.check_config": "R1"},
            "policy.risk_by_label": {kids: "R4"},
        },
        overrides={"entity:light.ceiling": {"policy.risk_override": "R1"}},
    )
    policy = rt.module("policy")
    assert policy.risk(ActionRequest("light", "turn_on", entity_ids=["light.hall"])) == Risk.R3
    assert policy.risk(ActionRequest("light", "turn_off", entity_ids=["light.hall"])) == Risk.R2
    assert policy.risk(ActionRequest("homeassistant", "turn_on", entity_ids=["light.hall"])) == Risk.R3
    assert policy.risk(ActionRequest("homeassistant", "check_config")) == Risk.R1
    assert policy.risk(ActionRequest("light", "turn_off", entity_ids=["light.kids"])) == Risk.R4  # label
    assert policy.risk(ActionRequest("light", "turn_on", entity_ids=["light.ceiling"])) == Risk.R1  # entity first
    assert classify("light", "turn_on", ["light.a"]) == Risk.R1  # without settings: built-in classes


def test_risk_table_validation() -> None:
    registry = build_registry()
    by_service = registry["policy.risk_by_service"]
    assert by_service.validate({"switch": "r3"}) == {"switch": "R3"}
    for bad in ({"Switch!": "R3"}, {"switch": "R9"}, {"switch": 3}, ["switch"]):
        with pytest.raises(SettingError):
            by_service.validate(bad)
    with pytest.raises(SettingError):
        registry["policy.risk_by_label"].validate({"a.b": "R1"})


def test_turning_off_a_playbook_needs_confirmation() -> None:
    playbooks = build_registry()["repair.playbooks"]
    everything = list(playbooks.default)
    assert playbooks.lowers_protection(everything, everything[1:])
    assert not playbooks.lowers_protection(everything[1:], everything)


async def test_playbooks_and_never_reload(hass: HomeAssistant) -> None:
    home = standard_home(hass)
    rt = await setup_homeai(hass, {"repair.playbooks": ["retry_backup", "action"]})
    [s] = await open_with(hass, rt, failing_integration(home.entry.entry_id))
    assert not s.repair.get("playbook")  # reloading is off: people are told instead
    runner = rt.module("repair")
    rt.settings.set("repair.playbooks", ["reload_entry"], confirmed=True)
    assert runner.plan(s) is not None
    rt.settings.set("repair.never_reload", [home.entry.domain])
    assert runner.plan(s) is None
    rt.settings.set("repair.never_reload", [home.entry.entry_id])
    assert runner.plan(s) is None


async def test_who_may_add_to_the_plan(hass: HomeAssistant, hass_admin_user, hass_read_only_user) -> None:
    home = standard_home(hass)
    home.person("guest", "Guest", user_id=hass_read_only_user.id)
    rt = await setup_homeai(
        hass, {"schedule.who_may_add": "residents"}, overrides={"person:person.guest": {"presence.role": "guest"}}
    )
    scheduler = rt.module("scheduler")
    reminder = {"reminder": "Water the plants", "when": {"kind": "daily", "time": "18:00"}}
    with pytest.raises(PlanError, match="not_allowed"):
        await scheduler.save(reminder, hass_read_only_user.id)
    rt.settings.set("presence.role", "member", skey="person:person.guest")
    assert (await scheduler.save(reminder, hass_read_only_user.id))["skip_when_away"] is False
    rt.settings.set("schedule.who_may_add", "admins")
    with pytest.raises(PlanError, match="admin_required"):
        await scheduler.save(reminder, hass_read_only_user.id)
    rt.settings.set("schedule.default_skip_when_away", True)
    entry = await scheduler.save(reminder, hass_admin_user.id)  # administrators always may
    assert entry["skip_when_away"] is True
    assert (await scheduler.save({**reminder, "skip_when_away": False}, None))["skip_when_away"] is False
