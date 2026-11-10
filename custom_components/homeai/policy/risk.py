"""Risk classes and how a service call is classified.

R0 read · R1 reversible comfort · R2 devices · R3 system · R4 configuration · R5 security · R6 destructive.
The class comes from the domain and service (or the administrator's `policy.risk_by_service` for a domain or a
`domain.service`), the entity's device class, the administrator's class for a label (`policy.risk_by_label`,
the highest among the entity's labels), then the override for an entity, device, area or floor
(`policy.risk_override`). The highest class among the targets wins.
"""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..settings import SettingsManager
    from ..world import WorldModel


class Risk(IntEnum):
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3
    R4 = 4
    R5 = 5
    R6 = 6

    @classmethod
    def parse(cls, value: object) -> Risk | None:
        if isinstance(value, Risk):
            return value
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 6:
            return cls(value)
        if isinstance(value, str) and len(value) == 2 and value[0] in "Rr" and value[1].isdigit():
            return cls.parse(int(value[1]))
        return None


DOMAIN_RISK: dict[str, Risk] = {
    # reversible comfort
    "light": Risk.R1,
    "fan": Risk.R1,
    "media_player": Risk.R1,
    "scene": Risk.R1,
    "notify": Risk.R1,
    "persistent_notification": Risk.R1,
    "tts": Risk.R1,
    "remote": Risk.R1,
    "input_boolean": Risk.R1,
    "input_number": Risk.R1,
    "input_select": Risk.R1,
    "input_text": Risk.R1,
    "input_datetime": Risk.R1,
    "input_button": Risk.R1,
    "counter": Risk.R1,
    "timer": Risk.R1,
    "number": Risk.R1,
    "select": Risk.R1,
    "text": Risk.R1,
    "humidifier": Risk.R1,
    "todo": Risk.R1,
    "calendar": Risk.R1,
    # devices
    "switch": Risk.R2,
    "cover": Risk.R2,
    "climate": Risk.R2,
    "water_heater": Risk.R2,
    "vacuum": Risk.R2,
    "lawn_mower": Risk.R2,
    "button": Risk.R2,
    "valve": Risk.R2,
    "script": Risk.R2,
    "automation": Risk.R2,
    "time": Risk.R2,
    "date": Risk.R2,
    "datetime": Risk.R2,
    "event": Risk.R2,
    # system
    "update": Risk.R4,
    "backup": Risk.R3,
    "hassio": Risk.R3,
    "recorder": Risk.R3,
    "logger": Risk.R3,
    "system_log": Risk.R1,
    "zone": Risk.R4,
    "person": Risk.R4,
    "group": Risk.R3,
    "template": Risk.R3,
    # security
    "lock": Risk.R5,
    "alarm_control_panel": Risk.R5,
    "camera": Risk.R5,
    "siren": Risk.R5,
}

SERVICE_RISK: dict[tuple[str, str], Risk] = {
    ("homeassistant", "turn_on"): Risk.R1,  # refined by targets
    ("homeassistant", "turn_off"): Risk.R1,
    ("homeassistant", "toggle"): Risk.R1,
    ("homeassistant", "update_entity"): Risk.R0,
    ("homeassistant", "reload_config_entry"): Risk.R3,
    ("homeassistant", "reload_core_config"): Risk.R3,
    ("homeassistant", "reload_all"): Risk.R3,
    ("homeassistant", "check_config"): Risk.R0,
    ("homeassistant", "restart"): Risk.R6,
    ("homeassistant", "stop"): Risk.R6,
    ("homeassistant", "set_location"): Risk.R4,
    ("backup", "create"): Risk.R3,
    ("backup", "create_automatic"): Risk.R3,
    ("hassio", "addon_restart"): Risk.R3,
    ("hassio", "addon_start"): Risk.R3,
    ("hassio", "addon_stop"): Risk.R4,
    ("hassio", "host_reboot"): Risk.R6,
    ("hassio", "host_shutdown"): Risk.R6,
    ("hassio", "backup_full"): Risk.R3,
    ("hassio", "backup_partial"): Risk.R3,
    ("hassio", "restore_full"): Risk.R6,
    ("hassio", "restore_partial"): Risk.R6,
    ("recorder", "purge"): Risk.R6,
    ("recorder", "purge_entities"): Risk.R6,
    ("recorder", "disable"): Risk.R4,
    ("automation", "reload"): Risk.R3,
    ("automation", "turn_off"): Risk.R4,
    ("automation", "turn_on"): Risk.R4,
    ("automation", "trigger"): Risk.R2,
    ("script", "reload"): Risk.R3,
    ("scene", "reload"): Risk.R3,
    ("scene", "create"): Risk.R1,
    ("scene", "delete"): Risk.R4,
    ("scene", "apply"): Risk.R1,
    ("update", "skip"): Risk.R3,
    ("update", "clear_skipped"): Risk.R3,
    ("camera", "snapshot"): Risk.R5,
    ("camera", "turn_on"): Risk.R5,
    ("camera", "turn_off"): Risk.R5,
    ("system_log", "clear"): Risk.R3,
    ("logger", "set_level"): Risk.R3,
    ("logger", "set_default_level"): Risk.R3,
    ("todo", "remove_item"): Risk.R2,
    ("todo", "remove_completed_items"): Risk.R2,
}

SECURITY_COVER_CLASSES = frozenset({"garage", "gate", "door"})

# Services that make things safer: allowed as protective actions on entities labelled by the administrator.
PROTECTIVE_SERVICES: frozenset[tuple[str, str]] = frozenset(
    {
        ("valve", "close_valve"),
        ("switch", "turn_off"),
        ("lock", "lock"),
        ("cover", "close_cover"),
        ("water_heater", "turn_off"),
        ("climate", "turn_off"),
        ("fan", "turn_on"),
        ("light", "turn_on"),
        ("siren", "turn_on"),
        ("alarm_control_panel", "alarm_arm_away"),
        ("alarm_control_panel", "alarm_arm_home"),
        ("alarm_control_panel", "alarm_arm_night"),
        ("media_player", "media_pause"),
        ("homeassistant", "turn_off"),
    }
)


def base_risk(domain: str, service: str) -> Risk:
    if domain == "config":  # configuration editing through HA's editors (see actions/config.py)
        if service.endswith(("_get", "_list")):
            return Risk.R0
        return Risk.R6 if service.endswith("_delete") else Risk.R4
    if (domain, service) in SERVICE_RISK:
        return SERVICE_RISK[(domain, service)]
    if service in ("reload",):
        return Risk.R3
    return DOMAIN_RISK.get(domain, Risk.R2)


def classify(
    domain: str,
    service: str,
    entity_ids: list[str] | tuple[str, ...] | set[str],
    *,
    world: WorldModel | None = None,
    settings: SettingsManager | None = None,
) -> Risk:
    """The risk of calling `domain.service` on these entities."""
    by_service = dict(settings.get("policy.risk_by_service") or {}) if settings is not None else {}
    by_label = dict(settings.get("policy.risk_by_label") or {}) if settings is not None else {}
    base = _configured(domain, service, by_service)
    if not entity_ids:
        return base
    risks = []
    for entity_id in entity_ids:
        e_domain = entity_id.split(".", 1)[0]
        risk = _configured(e_domain, service, by_service) if domain == "homeassistant" and service in _GENERIC else base
        info = world.entity(entity_id) if world is not None else None
        if e_domain == "cover" and info is not None and info.device_class in SECURITY_COVER_CLASSES:
            risk = max(risk, Risk.R5)
        if e_domain == "switch" and world is not None and _is_lock_like(world, entity_id):
            risk = max(risk, Risk.R5)
        if info is not None and by_label:
            labelled = [r for label in info.labels if (r := Risk.parse(by_label.get(label))) is not None]
            if labelled:
                risk = max(labelled)
        if settings is not None and world is not None:
            override = Risk.parse(settings.get("policy.risk_override", world.target(entity_id)))
            if override is not None:
                risk = override
        risks.append(risk)
    return max(risks)


def _configured(domain: str, service: str, by_service: dict[str, str]) -> Risk:
    """The built-in class, unless the administrator set one for this `domain.service` or the whole domain."""
    for key in (f"{domain}.{service}", domain):
        if (risk := Risk.parse(by_service.get(key))) is not None:
            return risk
    return base_risk(domain, service)


_GENERIC = frozenset({"turn_on", "turn_off", "toggle"})


def _is_lock_like(world: WorldModel, entity_id: str) -> bool:
    """A switch on a device that also has a lock or alarm entity (relay for a gate, door opener)."""
    info = world.entity(entity_id)
    if info is None or not info.device_id:
        return False
    return any(e.split(".", 1)[0] in ("lock", "alarm_control_panel") for e in world.of_device(info.device_id))


def is_protective(domain: str, service: str, entity_ids: list[str] | tuple[str, ...], world: WorldModel) -> bool:
    """A safe-direction service on entities the administrator labelled as protective actions."""
    if (domain, service) not in PROTECTIVE_SERVICES or not entity_ids:
        return False
    return all(world.has_label(e, "label_protective") for e in entity_ids)
