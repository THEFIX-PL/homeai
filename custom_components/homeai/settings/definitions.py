"""Declarations of every HomeAI setting, grouped by panel section.

Rules (enforced by tests): every behaviour-changing value lives here; every key has an English and a Polish
label and description in `i18n/`; defaults are valid. Modules read values through `SettingsManager.get`.
"""

from __future__ import annotations

from typing import Any

from .registry import Scope, Setting, SettingError, SettingsRegistry, SettingType as T

G = frozenset({Scope.GLOBAL})
PERSON = frozenset({Scope.GLOBAL, Scope.PERSON})
PLACE = frozenset({Scope.GLOBAL, Scope.FLOOR, Scope.AREA})
THING = frozenset({Scope.GLOBAL, Scope.FLOOR, Scope.AREA, Scope.DEVICE, Scope.ENTITY})
DEVICE_ENTITY = frozenset({Scope.GLOBAL, Scope.DEVICE, Scope.ENTITY})

ROLES = ("admin", "member", "guest", "ignore")
LADDER_TO = ("none", "all", "home", "home_or_all", "admins", "awake_home")
LADDER_CHANNELS = ("push", "persistent", "tts", "event")
CATEGORIES = ("safety", "security", "damage", "system", "energy", "comfort", "maintenance", "info")


def validate_ladder(value: Any) -> list[dict[str, Any]]:
    """Escalation ladder: a list of steps {after, to, channels, repeat?, critical?}."""
    if not isinstance(value, list) or len(value) > 10:
        raise SettingError("ladder: a list of up to 10 steps")
    steps = []
    for i, step in enumerate(value, start=1):
        if not isinstance(step, dict) or set(step) - {"after", "to", "channels", "repeat", "critical"}:
            raise SettingError(f"ladder step {i}: fields after, to, channels, repeat, critical")
        after, repeat = step.get("after", 0), step.get("repeat", 0)
        if not isinstance(after, int) or isinstance(after, bool) or not 0 <= after <= 1440:
            raise SettingError(f"ladder step {i}: after is 0–1440 minutes")
        if not isinstance(repeat, int) or isinstance(repeat, bool) or not 0 <= repeat <= 1440:
            raise SettingError(f"ladder step {i}: repeat is 0–1440 minutes")
        if step.get("to", "none") not in LADDER_TO:
            raise SettingError(f"ladder step {i}: to is one of {', '.join(LADDER_TO)}")
        channels = step.get("channels") or []
        if not isinstance(channels, list) or any(c not in LADDER_CHANNELS for c in channels):
            raise SettingError(f"ladder step {i}: channels from {', '.join(LADDER_CHANNELS)}")
        steps.append(
            {
                "after": after,
                "to": step.get("to", "none"),
                "channels": list(dict.fromkeys(channels)),
                "repeat": repeat,
                "critical": bool(step.get("critical", False)),
            }
        )
    return steps


def validate_severity_map(value: Any) -> dict[str, int]:
    """Kind → severity 0–4 overrides."""
    if not isinstance(value, dict):
        raise SettingError("an object of kind → severity")
    out = {}
    for kind, sev in value.items():
        if not isinstance(kind, str) or isinstance(sev, bool) or not isinstance(sev, int) or not 0 <= sev <= 4:
            raise SettingError(f"{kind}: severity 0–4")
        out[kind] = sev
    return out


def _sev(key: str, default: int, section: str, scopes: frozenset = G, advanced: bool = True) -> Setting:
    return Setting(key, T.INT, default, section, scopes=scopes, min=0, max=4, advanced=advanced)


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


def _detectors() -> list[Setting]:
    s = "detectors"
    out = [
        Setting("detectors.system_refresh", T.DURATION, 300, s, min=60, max=3600, unit="s", advanced=True),
    ]
    for key in (
        "safety",
        "security",
        "internet",
        "availability",
        "integrations",
        "backups",
        "updates",
        "log",
        "battery",
        "consumables",
        "problems",
        "stale",
        "environment",
        "divergence",
        "lights_away",
        "window_heating",
        "external",
        "bridges",
    ):
        out.append(
            Setting(
                f"detectors.{key}.enabled",
                T.BOOL,
                True,
                s,
                confirm="disable" if key in ("safety", "security") else None,
            )
        )
    out += [
        _sev("detectors.safety.severity_leak", 4, s, THING),
        _sev("detectors.safety.severity_smoke", 4, s, THING),
        _sev("detectors.safety.severity_gas", 4, s, THING),
        _sev("detectors.safety.severity_carbon_monoxide", 4, s, THING),
        _sev("detectors.safety.severity_safety", 3, s, THING),
        _sev("detectors.safety.severity_tamper", 2, s, THING),
        Setting("detectors.security.away_minutes", T.INT, 10, s, scopes=THING, min=0, max=720, unit="min"),
        Setting("detectors.security.night_minutes", T.INT, 30, s, scopes=THING, min=0, max=720, unit="min"),
        Setting("detectors.security.openings_at_night", T.BOOL, True, s, scopes=THING),
        Setting("detectors.internet.entity", T.ENTITY, "", s, selector="entity"),
        Setting("detectors.internet.minutes", T.INT, 2, s, min=0, max=120, unit="min"),
        _sev("detectors.internet.severity", 3, s),
        Setting("detectors.availability.minutes", T.INT, 15, s, scopes=THING, min=1, max=10080, unit="min"),
        _sev("detectors.availability.severity", 1, s, THING),
        _sev("detectors.integrations.severity", 1, s),
        Setting("detectors.integrations.repairs", T.BOOL, True, s),
        _sev("detectors.integrations.repairs_severity", 0, s),
        Setting("detectors.backups.max_age_hours", T.INT, 30, s, min=1, max=720, unit="h"),
        _sev("detectors.backups.severity", 1, s),
        _sev("detectors.updates.severity", 0, s),
        Setting("detectors.log.window_hours", T.INT, 24, s, min=1, max=168, unit="h", advanced=True),
        Setting("detectors.log.min_errors", T.INT, 1, s, min=1, max=1000, advanced=True),
        _sev("detectors.log.severity", 0, s),
        Setting("detectors.log.automations", T.BOOL, True, s),
        _sev("detectors.log.automation_severity", 1, s),
        Setting("detectors.battery.threshold", T.INT, 20, s, scopes=THING, min=1, max=99, unit="%"),
        _sev("detectors.battery.severity", 1, s, THING),
        _sev("detectors.battery.safety_severity", 2, s, THING),
        Setting("detectors.battery.group", T.BOOL, True, s),
        Setting("detectors.consumables.percent", T.INT, 10, s, scopes=THING, min=0, max=100, unit="%"),
        Setting("detectors.consumables.used_up_entities", T.ENTITIES, [], s, selector="entity", advanced=True),
        _sev("detectors.consumables.severity", 0, s, THING),
        _sev("detectors.problems.severity", 1, s, THING),
        _sev("detectors.problems.plant_severity", 1, s, THING),
        Setting("detectors.stale.hours", T.INT, 6, s, scopes=THING, min=0, max=720, unit="h"),
        _sev("detectors.stale.severity", 0, s, THING),
        Setting("detectors.environment.minutes", T.INT, 20, s, scopes=THING, min=0, max=1440, unit="min"),
        Setting("detectors.divergence.degrees", T.FLOAT, 2.5, s, scopes=PLACE, min=0.5, max=20, unit="°"),
        _sev("detectors.divergence.severity", 0, s),
        Setting("detectors.lights_away.minutes", T.INT, 10, s, scopes=THING, min=0, max=720, unit="min"),
        _sev("detectors.lights_away.severity", 2, s),
        Setting("detectors.window_heating.minutes", T.INT, 10, s, scopes=THING, min=0, max=720, unit="min"),
        _sev("detectors.window_heating.severity", 2, s, THING),
        Setting("detectors.external.attributes", T.BOOL, True, s, advanced=True),
    ]
    env = [
        ("temperature_min", 10.0, -20, 30, "°C", 3, True),
        ("temperature_max", 30.0, 15, 60, "°C", 1, True),
        ("humidity_max", 70.0, 30, 100, "%", 1, True),
        ("humidity_min", 25.0, 0, 60, "%", 0, False),
        ("co2_max", 1500.0, 400, 10000, "ppm", 1, True),
        ("pm25_max", 50.0, 1, 1000, "µg/m³", 1, True),
    ]
    for name, default, lo, hi, unit, sev, enabled in env:
        base = f"detectors.environment.{name}"
        out += [
            Setting(f"{base}_enabled", T.BOOL, enabled, s, scopes=THING),
            Setting(base, T.FLOAT, default, s, scopes=THING, min=lo, max=hi, unit=unit),
            _sev(f"{base}_severity", sev, s, THING),
        ]
    return out


def _situations() -> list[Setting]:
    s = "situations"
    out = [
        Setting("situations.min_duration", T.DURATION, 60, s, min=0, max=3600, unit="s"),
        Setting("situations.close_after", T.DURATION, 300, s, min=0, max=86400, unit="s"),
        Setting("situations.dismiss_days", T.INT, 7, s, min=1, max=365, unit="d"),
    ]
    defaults = {"safety": 0, "security": 30, "damage": 60}
    for category in CATEGORIES:
        if category in defaults:
            out.append(
                Setting(
                    f"situations.min_duration_{category}",
                    T.DURATION,
                    defaults[category],
                    s,
                    min=0,
                    max=3600,
                    unit="s",
                    advanced=True,
                )
            )
    return out


def _triage() -> list[Setting]:
    s = "triage"
    return [
        Setting("triage.severity_overrides", T.JSON, {}, s, advanced=True, validator=validate_severity_map),
        Setting("triage.raise_when_away", T.BOOL, True, s),
        Setting("triage.calibration_enabled", T.BOOL, True, s),
        Setting("triage.calibration_min_events", T.INT, 5, s, min=2, max=100, advanced=True),
        Setting("triage.calibration_dismiss_ratio", T.FLOAT, 0.6, s, min=0.1, max=1.0, advanced=True),
    ]


DEFAULT_LADDERS: dict[int, list[dict[str, Any]]] = {
    4: [{"after": 0, "to": "all", "channels": ["push", "persistent", "tts", "event"], "repeat": 5, "critical": True}],
    3: [
        {"after": 0, "to": "home_or_all", "channels": ["push", "persistent", "event"], "repeat": 0, "critical": False},
        {"after": 15, "to": "all", "channels": ["push"], "repeat": 0, "critical": False},
    ],
    2: [{"after": 0, "to": "home_or_all", "channels": ["push", "event"], "repeat": 0, "critical": False}],
    1: [{"after": 0, "to": "none", "channels": ["persistent", "event"], "repeat": 0, "critical": False}],
    0: [],
}


def _notify() -> list[Setting]:
    s = "notify"
    out = [
        Setting("notify.paused", T.BOOL, False, s, confirm="change"),
        Setting("notify.paused_allows_critical", T.BOOL, True, s, confirm="disable"),
        Setting("notify.targets", T.STRINGS, [], s, scopes=PERSON, selector="notify"),
        Setting("notify.discover_apps", T.BOOL, True, s, scopes=PERSON),
        Setting("notify.include_tablets", T.BOOL, False, s, scopes=PERSON),
        Setting("notify.max_per_day", T.INT, 20, s, min=1, max=500),
        Setting("notify.critical_sound", T.BOOL, True, s),
        Setting("notify.snooze_minutes", T.INT, 240, s, min=5, max=10080, unit="min"),
        Setting("notify.announce_resolved", T.BOOL, False, s),
        Setting("notify.open_path", T.STRING, "homeai", s, advanced=True, max=100),
        Setting("notify.tts_entity", T.ENTITY, "", s, selector="tts"),
        Setting("notify.tts_players", T.ENTITIES, [], s, selector="media_player"),
        Setting("notify.digest_enabled", T.BOOL, True, s),
        Setting("notify.digest_times", T.STRINGS, ["08:00", "20:00"], s, max=6),
        Setting("notify.digest_to", T.SELECT, "home_or_all", s, options=LADDER_TO),
        Setting("notify.digest_max_items", T.INT, 10, s, min=1, max=50),
    ]
    for sev in (4, 3, 2, 1, 0):
        out.append(
            Setting(
                f"notify.ladder_{sev}",
                T.JSON,
                DEFAULT_LADDERS[sev],
                s,
                advanced=sev < 2,
                validator=validate_ladder,
                confirm="change" if sev >= 3 else None,
            )
        )
    return out


LEVELS = ("never", "observe", "propose", "act_tell", "act")
RISK_OVERRIDES = ("auto", "R0", "R1", "R2", "R3", "R4", "R5", "R6")


def _policy() -> list[Setting]:
    s = "policy"
    out = [
        Setting("policy.autonomy_r1", T.SELECT, "act_tell", s, options=LEVELS, confirm="change"),
        Setting("policy.autonomy_r2", T.SELECT, "propose", s, options=LEVELS, confirm="change"),
        Setting("policy.autonomy_r3", T.SELECT, "act", s, options=LEVELS, confirm="change"),
        Setting(
            "policy.autonomy_r4", T.SELECT, "propose", s, options=("never", "observe", "propose"), confirm="change"
        ),
        Setting("policy.person_r2", T.SELECT, "act", s, options=("act", "confirm")),
        Setting("policy.observation_days", T.INT, 14, s, min=0, max=90, unit="d", confirm="lower"),
        Setting("policy.protective_actions", T.BOOL, True, s, confirm="disable"),
        Setting("policy.repairs_per_day", T.INT, 10, s, min=1, max=100, advanced=True),
        Setting("policy.approval_minutes", T.INT, 120, s, min=5, max=10080, unit="min"),
        Setting(
            "policy.risk_override",
            T.SELECT,
            "auto",
            s,
            scopes=THING,
            options=RISK_OVERRIDES,
            advanced=True,
            confirm="change",
        ),
    ]
    return out


def _executor() -> list[Setting]:
    s = "executor"
    return [
        Setting("executor.timeout", T.DURATION, 30, s, min=5, max=300, unit="s", advanced=True),
        Setting("executor.verify_seconds", T.DURATION, 10, s, min=0, max=120, unit="s", advanced=True),
        Setting("executor.undo", T.BOOL, True, s),
        Setting("executor.undo_keep", T.INT, 20, s, min=1, max=100, advanced=True),
        Setting("executor.block_cloud_offline", T.BOOL, True, s, advanced=True),
        Setting("executor.local_url", T.STRING, "", s, max=200, advanced=True),
    ]


def _repair() -> list[Setting]:
    s = "repair"
    return [
        Setting("repair.enabled", T.BOOL, True, s, confirm="disable"),
        Setting("repair.quick_actions", T.BOOL, True, s),
        Setting("repair.protective_enabled", T.BOOL, True, s, confirm="disable"),
        Setting("repair.max_attempts", T.INT, 2, s, min=1, max=5),
        Setting("repair.backoff_minutes", T.INT, 10, s, min=1, max=240, unit="min", advanced=True),
        Setting("repair.verify_minutes", T.INT, 5, s, min=1, max=120, unit="min", advanced=True),
        Setting("repair.reload_wait", T.INT, 2, s, min=0, max=120, unit="min", advanced=True),
        Setting("repair.retry_wait", T.INT, 10, s, min=0, max=240, unit="min", advanced=True),
        Setting("repair.outage_wait", T.INT, 5, s, min=0, max=240, unit="min", advanced=True),
        Setting("repair.backup_wait", T.INT, 30, s, min=0, max=1440, unit="min", advanced=True),
        Setting("repair.action_wait", T.INT, 0, s, min=0, max=240, unit="min", advanced=True),
    ]


def _adapters() -> list[Setting]:
    s = "adapters"
    return [
        Setting("adapters.auto_bridges", T.BOOL, True, s),
        Setting("adapters.bridge_entities", T.ENTITIES, [], s, selector="entity"),
        Setting("adapters.bridge_minutes", T.INT, 2, s, scopes=THING, min=0, max=120, unit="min"),
        _sev("adapters.bridge_severity", 3, s, THING),
        Setting("adapters.bridge_reload", T.BOOL, True, s),
        Setting("adapters.zigbee2mqtt_addon", T.STRING, "", s, max=100, advanced=True),
    ]


def _schedule() -> list[Setting]:
    s = "schedule"
    return [
        Setting("schedule.catch_up_minutes", T.INT, 10, s, min=0, max=240, unit="min"),
        Setting("schedule.event_minutes", T.INT, 15, s, min=1, max=240, unit="min", advanced=True),
        Setting("schedule.presence_keep_days", T.INT, 30, s, min=1, max=365, unit="d", advanced=True),
    ]


def _ai() -> list[Setting]:
    s = "ai"
    return [
        Setting("ai.enabled", T.BOOL, True, s),
        Setting("ai.triage_enabled", T.BOOL, True, s),
        Setting("ai.triage_confidence", T.FLOAT, 0.9, s, min=0, max=1, step=0.05, advanced=True),
        Setting("ai.triage_new_kinds", T.BOOL, True, s, advanced=True),
        Setting("ai.p2_confidence", T.FLOAT, 0.6, s, min=0, max=1, step=0.05),
        Setting("ai.p2_min_severity", T.INT, 3, s, min=0, max=5),
        Setting("ai.narrate_digest", T.BOOL, True, s),
        Setting("ai.p2_max_steps", T.INT, 8, s, min=1, max=30, advanced=True),
        Setting("ai.chat_tier", T.SELECT, "p1", s, options=("p1", "p2")),
        Setting("ai.chat_max_steps", T.INT, 6, s, min=1, max=20, advanced=True),
        Setting("ai.chat_turns", T.INT, 10, s, min=1, max=50, advanced=True),
        Setting("ai.budget_mode", T.SELECT, "block", s, options=("warn", "block"), confirm="change"),
        Setting("ai.budget_daily", T.FLOAT, 1.0, s, min=0, max=1000, step=0.1, unit="$"),
        Setting("ai.budget_monthly", T.FLOAT, 10.0, s, min=0, max=10000, step=1, unit="$"),
        Setting("ai.budget_warn_percent", T.INT, 80, s, min=10, max=100, unit="%"),
        Setting("ai.max_calls_per_hour", T.INT, 60, s, min=1, max=10000, advanced=True),
        Setting("ai.timeout", T.DURATION, 90, s, min=10, max=600, unit="s", advanced=True),
        Setting("ai.p3_timeout", T.DURATION, 900, s, min=60, max=3600, unit="s", advanced=True),
        Setting("ai.arbiter_enabled", T.BOOL, True, s),
        Setting("ai.arbiter_disputes", T.BOOL, True, s),
        Setting("ai.arbiter_approvals", T.BOOL, True, s),
        Setting("ai.arbiter_failed_repairs", T.BOOL, True, s),
        Setting("ai.arbiter_can_approve", T.BOOL, False, s, confirm="change"),
        Setting("ai.arbiter_min_confidence", T.FLOAT, 0.8, s, min=0.5, max=1, step=0.05, advanced=True),
        Setting("ai.arbiter_effort", T.SELECT, "high", s, options=("medium", "high", "xhigh", "max"), advanced=True),
        Setting("ai.arbiter_per_day", T.INT, 10, s, min=1, max=200),
    ]


def _learning() -> list[Setting]:
    s = "learning"
    return [
        Setting("learning.enabled", T.BOOL, True, s),
        Setting("learning.nightly_time", T.TIME, "03:17", s, advanced=True),
        Setting("learning.baseline_weeks", T.INT, 4, s, min=1, max=12, unit="wk", advanced=True),
        Setting("learning.min_samples", T.INT, 100, s, min=10, max=5000, advanced=True),
        Setting("detectors.anomaly.enabled", T.BOOL, True, s),
        Setting("learning.anomaly_sigma", T.FLOAT, 3.0, s, min=1.5, max=10, step=0.5),
        Setting("learning.anomaly_minutes", T.INT, 30, s, scopes=THING, min=5, max=720, unit="min"),
        _sev("learning.anomaly_severity", 1, s, THING),
        Setting("learning.habits", T.BOOL, True, s),
        Setting("learning.habit_days", T.INT, 21, s, min=7, max=60, unit="d", advanced=True),
        Setting("learning.habit_min_days", T.INT, 8, s, min=3, max=60, unit="d", advanced=True),
        Setting("learning.habit_window", T.INT, 20, s, min=5, max=90, unit="min", advanced=True),
        Setting("learning.undo_limit", T.INT, 2, s, min=1, max=20),
        Setting("learning.deny_quiet_days", T.INT, 14, s, min=1, max=365, unit="d"),
        Setting("learning.raise_after", T.INT, 5, s, min=2, max=100, advanced=True),
        Setting("learning.review_weekday", T.SELECT, "6", s, options=("0", "1", "2", "3", "4", "5", "6")),
        Setting("learning.review_time", T.TIME, "18:43", s),
        Setting("learning.review_push", T.BOOL, True, s),
        Setting("learning.review_ai", T.BOOL, True, s),
    ]


SECTIONS = [
    _general,
    _world,
    _presence,
    _privacy,
    _detectors,
    _situations,
    _triage,
    _notify,
    _policy,
    _executor,
    _repair,
    _adapters,
    _schedule,
    _ai,
    _learning,
]


def build_registry() -> SettingsRegistry:
    """All settings, in panel order."""
    registry = SettingsRegistry()
    for group in SECTIONS:
        registry.add(*group())
    return registry
