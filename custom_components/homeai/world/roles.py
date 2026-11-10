"""What an entity is for, derived from its domain, device class, unit and capabilities — never from its name."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import re
from typing import Any


class Role(StrEnum):
    LIGHT = "light"
    OUTLET = "outlet"
    SWITCH = "switch"
    FAN = "fan"
    CLIMATE = "climate"
    WATER_HEATER = "water_heater"
    HUMIDIFIER = "humidifier"
    COVER = "cover"
    GARAGE_DOOR = "garage_door"
    GATE = "gate"
    LOCK = "lock"
    VALVE = "valve"
    WATER_VALVE = "water_valve"
    ALARM_PANEL = "alarm_panel"
    VACUUM = "vacuum"
    LAWN_MOWER = "lawn_mower"
    MEDIA_PLAYER = "media_player"
    CAMERA = "camera"
    SIREN = "siren"
    SCENE = "scene"
    SCRIPT = "script"
    AUTOMATION = "automation"
    BUTTON = "button"
    SELECT = "select"
    NUMBER = "number"
    UPDATE = "update"
    CALENDAR = "calendar"
    TODO = "todo"
    WEATHER = "weather"
    PERSON = "person"
    DEVICE_TRACKER = "device_tracker"
    PLANT = "plant"
    # binary sensors
    OPENING = "opening"  # door / window / opening / garage door contact
    WINDOW = "window"
    DOOR = "door"
    LEAK = "leak"  # moisture binary sensor
    SMOKE = "smoke"
    GAS = "gas"
    CARBON_MONOXIDE = "carbon_monoxide"
    SAFETY = "safety"
    TAMPER = "tamper"
    PROBLEM = "problem"
    MOTION = "motion"
    OCCUPANCY = "occupancy"
    PRESENCE = "presence"
    RUNNING = "running"
    BATTERY_LOW = "battery_low"
    CONNECTIVITY = "connectivity"
    PLUG = "plug"
    POWER_STATE = "power_state"
    # sensors
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    SOIL_MOISTURE = "soil_moisture"
    CO2 = "co2"
    PM25 = "pm25"
    VOC = "voc"
    ILLUMINANCE = "illuminance"
    BATTERY = "battery"
    POWER = "power"
    ENERGY = "energy"
    WATER = "water"
    GAS_VOLUME = "gas_volume"
    TIMESTAMP = "timestamp"
    LAST_SEEN = "last_seen"
    CONSUMABLE = "consumable"  # remaining life of a filter, brush, cartridge… (percent or hours)
    SIGNAL = "signal"
    # anything that can be switched on/off and changes the home
    CONTROLLABLE = "controllable"


CONTROL_DOMAINS = frozenset(
    {
        "light",
        "switch",
        "fan",
        "climate",
        "water_heater",
        "humidifier",
        "cover",
        "lock",
        "valve",
        "alarm_control_panel",
        "vacuum",
        "lawn_mower",
        "media_player",
        "siren",
        "remote",
        "camera",
    }
)

_DOMAIN_ROLES: dict[str, Role] = {
    "light": Role.LIGHT,
    "fan": Role.FAN,
    "climate": Role.CLIMATE,
    "water_heater": Role.WATER_HEATER,
    "humidifier": Role.HUMIDIFIER,
    "cover": Role.COVER,
    "lock": Role.LOCK,
    "valve": Role.VALVE,
    "alarm_control_panel": Role.ALARM_PANEL,
    "vacuum": Role.VACUUM,
    "lawn_mower": Role.LAWN_MOWER,
    "media_player": Role.MEDIA_PLAYER,
    "camera": Role.CAMERA,
    "siren": Role.SIREN,
    "scene": Role.SCENE,
    "script": Role.SCRIPT,
    "automation": Role.AUTOMATION,
    "button": Role.BUTTON,
    "input_button": Role.BUTTON,
    "select": Role.SELECT,
    "input_select": Role.SELECT,
    "number": Role.NUMBER,
    "input_number": Role.NUMBER,
    "update": Role.UPDATE,
    "calendar": Role.CALENDAR,
    "todo": Role.TODO,
    "weather": Role.WEATHER,
    "person": Role.PERSON,
    "device_tracker": Role.DEVICE_TRACKER,
    "plant": Role.PLANT,
}

_BINARY: dict[str, tuple[Role, ...]] = {
    "door": (Role.OPENING, Role.DOOR),
    "garage_door": (Role.OPENING, Role.DOOR),
    "window": (Role.OPENING, Role.WINDOW),
    "opening": (Role.OPENING,),
    "moisture": (Role.LEAK,),
    "smoke": (Role.SMOKE,),
    "gas": (Role.GAS,),
    "carbon_monoxide": (Role.CARBON_MONOXIDE,),
    "safety": (Role.SAFETY,),
    "tamper": (Role.TAMPER,),
    "problem": (Role.PROBLEM,),
    "motion": (Role.MOTION,),
    "moving": (Role.MOTION,),
    "occupancy": (Role.OCCUPANCY,),
    "presence": (Role.PRESENCE,),
    "running": (Role.RUNNING,),
    "battery": (Role.BATTERY_LOW,),
    "connectivity": (Role.CONNECTIVITY,),
    "plug": (Role.PLUG,),
    "power": (Role.POWER_STATE,),
}

_SENSOR: dict[str, Role] = {
    "temperature": Role.TEMPERATURE,
    "humidity": Role.HUMIDITY,
    "moisture": Role.SOIL_MOISTURE,
    "carbon_dioxide": Role.CO2,
    "pm25": Role.PM25,
    "volatile_organic_compounds": Role.VOC,
    "volatile_organic_compounds_parts": Role.VOC,
    "illuminance": Role.ILLUMINANCE,
    "battery": Role.BATTERY,
    "power": Role.POWER,
    "energy": Role.ENERGY,
    "water": Role.WATER,
    "gas": Role.GAS_VOLUME,
    "timestamp": Role.TIMESTAMP,
    "signal_strength": Role.SIGNAL,
}

_CONSUMABLE = re.compile(r"(filter|brush|mop|strainer|cartridge|blade|consumable|life|remaining|time_left)", re.I)
_LAST_SEEN = re.compile(r"(last_seen|last_activity|last_seen_at)$", re.I)


def classify(
    domain: str,
    attributes: Mapping[str, Any],
    *,
    device_class: str | None = None,
    translation_key: str | None = None,
    entity_id: str = "",
) -> frozenset[Role]:
    """Roles of one entity. `device_class` from the registry wins over the state attribute."""
    roles: set[Role] = set()
    dc = device_class or attributes.get("device_class")
    unit = attributes.get("unit_of_measurement")
    if domain in CONTROL_DOMAINS:
        roles.add(Role.CONTROLLABLE)
    if (r := _DOMAIN_ROLES.get(domain)) is not None:
        roles.add(r)
    if domain == "switch":
        roles.add(Role.OUTLET if dc == "outlet" else Role.SWITCH)
    elif domain == "cover" and dc in ("garage", "gate"):
        roles.add(Role.GARAGE_DOOR if dc == "garage" else Role.GATE)
    elif domain == "valve" and dc == "water":
        roles.add(Role.WATER_VALVE)
    elif domain == "binary_sensor" and dc in _BINARY:
        roles.update(_BINARY[dc])
    elif domain == "sensor":
        if dc in _SENSOR:
            roles.add(_SENSOR[dc])
        if dc == "timestamp" and _LAST_SEEN.search(f"{translation_key or ''} {entity_id}"):
            roles.add(Role.LAST_SEEN)
        if (
            dc not in ("battery", "humidity", "moisture")
            and unit in ("%", "h", "d")
            and _CONSUMABLE.search(f"{translation_key or ''} {entity_id.partition('.')[2]}")
        ):
            roles.add(Role.CONSUMABLE)
    return frozenset(roles)
