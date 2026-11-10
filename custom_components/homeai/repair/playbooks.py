"""Playbooks: what HomeAI does first for a kind of trouble. Each returns the actions to run.

A signal names its playbook in `signal.repair = {"playbook": key, ...params}`. Suggested quick actions
(`signal.action`) run through the same machinery under the `action` playbook, at their own risk class.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..policy import ActionRequest
from ..situations.model import Situation


@dataclass(frozen=True, slots=True)
class Playbook:
    key: str
    wait_setting: str  # minutes to wait before the first attempt
    build: Callable[[Any, Situation, dict[str, Any]], list[ActionRequest]]
    actor: str = "repair"


def _reload(rt: Any, s: Situation, params: dict[str, Any]) -> list[ActionRequest]:
    entry_id = params.get("entry_id")
    if not entry_id or rt.hass.config_entries.async_get_entry(entry_id) is None:
        return []
    return [
        ActionRequest(
            "homeassistant",
            "reload_config_entry",
            {"entry_id": entry_id},
            reason=s.title(rt.language),
            situation_id=s.id,
        )
    ]


def _backup(rt: Any, s: Situation, params: dict[str, Any]) -> list[ActionRequest]:
    if params.get("paused") or not rt.hass.services.has_service("backup", "create_automatic"):
        return []
    return [ActionRequest("backup", "create_automatic", {}, reason=s.title(rt.language), situation_id=s.id)]


def _addon(rt: Any, s: Situation, params: dict[str, Any]) -> list[ActionRequest]:
    addon = params.get("addon")
    if not addon or not rt.hass.services.has_service("hassio", "addon_restart"):
        return []
    return [ActionRequest("hassio", "addon_restart", {"addon": addon}, reason=s.title(rt.language), situation_id=s.id)]


def _action(rt: Any, s: Situation, params: dict[str, Any]) -> list[ActionRequest]:
    service = str(params.get("service") or "")
    domain, _, name = service.partition(".")
    if not domain or not name:
        return []
    return [
        ActionRequest(
            domain, name, dict(params.get("data") or {}), actor="homeai", reason=s.title(rt.language), situation_id=s.id
        )
    ]


PLAYBOOKS: dict[str, Playbook] = {
    "reload_entry": Playbook("reload_entry", "repair.reload_wait", _reload),
    "wait_then_reload": Playbook("wait_then_reload", "repair.retry_wait", _reload),
    "reload_after_outage": Playbook("reload_after_outage", "repair.outage_wait", _reload),
    "retry_backup": Playbook("retry_backup", "repair.backup_wait", _backup),
    "restart_addon": Playbook("restart_addon", "repair.reload_wait", _addon),
    "action": Playbook("action", "repair.action_wait", _action, actor="homeai"),
}

# Protective actions: when a safety situation opens, entities labelled “HomeAI: protective action” (in the
# same area first, else anywhere) get these safe-direction services. Policy still checks each one.
PROTECTIVE: dict[str, tuple[tuple[str, str], ...]] = {
    "leak": (("valve", "close_valve"), ("switch", "turn_off")),
    "gas": (("valve", "close_valve"), ("switch", "turn_off")),
    "smoke": (("climate", "turn_off"), ("water_heater", "turn_off")),
    "carbon_monoxide": (("fan", "turn_on"), ("climate", "turn_off"), ("water_heater", "turn_off")),
}


def protective_requests(rt: Any, s: Situation) -> list[ActionRequest]:
    p = s.primary
    if p is None or p.kind not in PROTECTIVE:
        return []
    world = rt.world
    labelled = {e for e in world.entities if world.has_label(e, "label_protective")}
    if not labelled:
        return []
    local = {e for e in labelled if p.area_id and world.entity(e) and world.entity(e).area_id == p.area_id}
    pool = local or labelled
    out = []
    for domain, service in PROTECTIVE[p.kind]:
        ids = sorted(e for e in pool if e.split(".", 1)[0] == domain)
        if ids:
            out.append(
                ActionRequest(
                    domain,
                    service,
                    {},
                    entity_ids=ids,
                    actor="homeai",
                    reason=s.title(rt.language),
                    situation_id=s.id,
                    playbook="protective",
                )
            )
    return out
