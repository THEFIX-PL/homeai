"""Declarations of every HomeAI setting, grouped by panel section.

Rules (enforced by tests): every behaviour-changing value lives here; every key has an English and a Polish
label and description in `i18n/`; defaults are valid. Modules read values through `SettingsManager.get`.
"""

from __future__ import annotations

from .registry import Scope, Setting, SettingsRegistry, SettingType as T

G = frozenset({Scope.GLOBAL})
PERSON = frozenset({Scope.GLOBAL, Scope.PERSON})
PLACE = frozenset({Scope.GLOBAL, Scope.FLOOR, Scope.AREA})
THING = frozenset({Scope.GLOBAL, Scope.FLOOR, Scope.AREA, Scope.DEVICE, Scope.ENTITY})
DEVICE_ENTITY = frozenset({Scope.GLOBAL, Scope.DEVICE, Scope.ENTITY})

ROLES = ("admin", "member", "guest", "ignore")


def _general() -> list[Setting]:
    s = "general"
    return [
        Setting("general.language", T.SELECT, "auto", s, options=("auto", "en", "pl")),
        Setting("general.assistant_name", T.STRING, "HomeAI", s, max=40),
        Setting("general.startup_grace", T.DURATION, 120, s, min=0, max=1800, unit="s", advanced=True),
        Setting("general.tick_seconds", T.DURATION, 60, s, min=10, max=600, unit="s", advanced=True, live=False),
        Setting("general.night_start", T.TIME, "23:00", s),
        Setting("general.morning_start", T.TIME, "06:00", s),
        Setting("general.day_start", T.TIME, "10:00", s),
        Setting("general.evening_start", T.TIME, "18:00", s),
        Setting("general.journal_retention_days", T.INT, 30, s, min=1, max=365, unit="d"),
        Setting("general.panel_sidebar", T.BOOL, True, s, live=False),
        Setting("general.panel_admin_only", T.BOOL, False, s, live=False),
    ]


def _world() -> list[Setting]:
    s = "world"
    return [
        Setting("world.scope", T.SELECT, "all", s, options=("all", "exposed", "selected")),
        Setting("world.include_areas", T.STRINGS, [], s, selector="area", depends_on=("world.scope", "selected")),
        Setting("world.include_domains", T.STRINGS, [], s, selector="domain", advanced=True),
        Setting("world.exclude_entities", T.STRINGS, [], s, advanced=True),
        Setting("world.include_hidden", T.BOOL, False, s, advanced=True),
        Setting("world.create_labels", T.BOOL, True, s),
        Setting("world.label_ignore", T.STRING, "homeai_ignore", s, selector="label", advanced=True),
        Setting("world.label_personal", T.STRING, "homeai_personal", s, selector="label", advanced=True),
        Setting("world.label_critical", T.STRING, "homeai_critical", s, selector="label", advanced=True),
        Setting("world.label_protective", T.STRING, "homeai_protective_action", s, selector="label", advanced=True),
        Setting("world.label_private", T.STRING, "homeai_private", s, selector="label", advanced=True),
    ]


def _presence() -> list[Setting]:
    s = "presence"
    return [
        Setting("presence.role", T.SELECT, "member", s, scopes=PERSON, options=ROLES),
        Setting("presence.home_mode_entity", T.ENTITY, "", s, selector="entity"),
        Setting("presence.vacation_states", T.STRINGS, ["vacation", "away"], s, advanced=True),
        Setting(
            "presence.sleep_sources",
            T.MULTISELECT,
            ["helper", "sensors", "ai", "hours"],
            s,
            options=("helper", "sensors", "ai", "hours"),
        ),
        Setting("presence.sleep_helper", T.ENTITY, "", s, scopes=PERSON, selector="entity"),
        Setting("presence.sleep_helper_state", T.STRING, "on", s, scopes=PERSON, advanced=True),
        Setting("presence.night_start", T.TIME, "23:00", s, scopes=PERSON),
        Setting("presence.night_end", T.TIME, "07:00", s, scopes=PERSON),
        Setting("presence.weekend_night_start", T.TIME, "00:00", s, scopes=PERSON),
        Setting("presence.weekend_night_end", T.TIME, "09:00", s, scopes=PERSON),
        Setting("presence.charging_entities", T.ENTITIES, [], s, scopes=PERSON, selector="entity"),
        Setting("presence.bed_entities", T.ENTITIES, [], s, scopes=PERSON, selector="entity"),
        Setting("presence.quiet_minutes", T.INT, 30, s, min=5, max=240, unit="min", advanced=True),
    ]


def _privacy() -> list[Setting]:
    s = "privacy"
    return [
        Setting("privacy.level", T.SELECT, "standard", s, options=("standard", "minimal", "full"), confirm="change"),
        Setting("privacy.never_send_entities", T.STRINGS, [], s, selector="entity"),
        Setting("privacy.never_send_areas", T.STRINGS, [], s, selector="area"),
        Setting("privacy.log_prompts", T.BOOL, False, s, advanced=True),
        Setting("privacy.log_retention_days", T.INT, 7, s, min=1, max=90, unit="d", advanced=True),
    ]


SECTIONS = [_general, _world, _presence, _privacy]


def build_registry() -> SettingsRegistry:
    """All settings, in panel order."""
    registry = SettingsRegistry()
    for group in SECTIONS:
        registry.add(*group())
    return registry
