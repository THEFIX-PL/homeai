"""Settings registry: every value that changes HomeAI's behaviour is declared here exactly once.

A `Setting` describes the type, default, allowed range, the scopes where it may be overridden, where it
appears in the panel and whether changing it needs an administrator or an explicit confirmation. Validation,
the settings panel, export/import and the generated documentation all come from these declarations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum
import re
from typing import Any


class SettingType(StrEnum):
    """Value types understood by validation and by the panel's form renderer."""

    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    TEXT = "text"  # multi-line string (prompts, templates)
    SELECT = "select"
    MULTISELECT = "multiselect"
    TIME = "time"  # "HH:MM"
    DURATION = "duration"  # seconds (int)
    ENTITY = "entity"
    ENTITIES = "entities"
    STRINGS = "strings"  # list of free strings (patterns, keywords)
    JSON = "json"  # structured value validated by a custom validator


class Scope(StrEnum):
    """Where a setting may be overridden. Resolution order: entity → device → area → floor → person → global."""

    GLOBAL = "global"
    FLOOR = "floor"
    AREA = "area"
    DEVICE = "device"
    ENTITY = "entity"
    PERSON = "person"


RESOLUTION_ORDER: tuple[Scope, ...] = (
    Scope.ENTITY,
    Scope.DEVICE,
    Scope.AREA,
    Scope.FLOOR,
    Scope.PERSON,
    Scope.GLOBAL,
)

KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SettingError(ValueError):
    """A value or an override does not satisfy the setting's declaration."""


@dataclass(frozen=True, slots=True)
class Setting:
    """Declaration of one configurable value."""

    key: str
    type: SettingType
    default: Any
    section: str
    scopes: frozenset[Scope] = frozenset({Scope.GLOBAL})
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str | None = None
    options: tuple[str, ...] = ()
    advanced: bool = False
    admin_only: bool = True
    # Changing the value away from the default in this direction lowers protection: "lower", "higher", "change".
    confirm: str | None = None
    live: bool = True  # False → the owning module reloads to apply it
    depends_on: tuple[str, Any] | None = None
    # Hint for the panel's form: "area", "label", "domain", "person", "notify", "media_player", "tts", "model"…
    selector: str | None = None
    validator: Any = field(default=None, compare=False)  # callable(value) -> value, raises SettingError

    def __post_init__(self) -> None:
        if not KEY_RE.match(self.key):
            raise ValueError(f"Bad setting key {self.key!r}")
        if Scope.GLOBAL not in self.scopes:
            raise ValueError(f"{self.key}: every setting must have a global value")
        self.validate(self.default)

    @property
    def group(self) -> str:
        """Second-level grouping in the panel (`detectors.battery.threshold` → `battery`)."""
        parts = self.key.split(".")
        return parts[1] if len(parts) > 2 else ""

    def validate(self, value: Any) -> Any:
        """Return the normalised value or raise SettingError."""
        t = self.type
        if t is SettingType.BOOL:
            if not isinstance(value, bool):
                raise SettingError(f"{self.key}: expected true or false")
            return value
        if t in (SettingType.INT, SettingType.DURATION):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
                raise SettingError(f"{self.key}: expected a whole number")
            return self._range(int(value))
        if t is SettingType.FLOAT:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingError(f"{self.key}: expected a number")
            return self._range(float(value))
        if t in (SettingType.STRING, SettingType.TEXT):
            if not isinstance(value, str):
                raise SettingError(f"{self.key}: expected text")
            if self.max is not None and len(value) > self.max:
                raise SettingError(f"{self.key}: at most {int(self.max)} characters")
            return value if t is SettingType.TEXT else value.strip()
        if t is SettingType.SELECT:
            if value not in self.options:
                raise SettingError(f"{self.key}: one of {', '.join(self.options)}")
            return value
        if t is SettingType.MULTISELECT:
            if not isinstance(value, (list, tuple)) or any(v not in self.options for v in value):
                raise SettingError(f"{self.key}: a list from {', '.join(self.options)}")
            return list(dict.fromkeys(value))
        if t is SettingType.TIME:
            if not isinstance(value, str) or not TIME_RE.match(value):
                raise SettingError(f"{self.key}: time as HH:MM")
            return value
        if t is SettingType.ENTITY:
            if value in (None, ""):
                return ""
            if not isinstance(value, str) or "." not in value:
                raise SettingError(f"{self.key}: an entity ID")
            return value
        if t in (SettingType.ENTITIES, SettingType.STRINGS):
            if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
                raise SettingError(f"{self.key}: a list of texts")
            if t is SettingType.ENTITIES and any("." not in v for v in value):
                raise SettingError(f"{self.key}: a list of entity IDs")
            items = [v.strip() for v in value if v.strip()]
            if self.max is not None and len(items) > self.max:
                raise SettingError(f"{self.key}: at most {int(self.max)} items")
            return list(dict.fromkeys(items))
        if t is SettingType.JSON:
            if self.validator is None:
                raise SettingError(f"{self.key}: no validator")
            return self.validator(value)
        raise SettingError(f"{self.key}: unknown type {t}")

    def _range(self, value: float) -> Any:
        if self.min is not None and value < self.min:
            raise SettingError(f"{self.key}: at least {self.min:g}")
        if self.max is not None and value > self.max:
            raise SettingError(f"{self.key}: at most {self.max:g}")
        return value

    def lowers_protection(self, old: Any, new: Any) -> bool:
        """Whether changing `old` → `new` needs an explicit confirmation."""
        if self.confirm is None or old == new:
            return False
        if self.confirm == "change":
            return True
        try:
            if self.confirm == "lower":
                return new < old
            if self.confirm == "higher":
                return new > old
        except TypeError:
            return True
        if self.confirm == "disable":
            return old is True and new is False
        return True

    def describe(self) -> dict[str, Any]:
        """Machine-readable description for the panel (labels are added by the i18n layer)."""
        return {
            "key": self.key,
            "type": str(self.type),
            "default": self.default,
            "section": self.section,
            "group": self.group,
            "scopes": sorted(str(s) for s in self.scopes),
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "unit": self.unit,
            "options": list(self.options),
            "advanced": self.advanced,
            "admin_only": self.admin_only,
            "confirm": self.confirm,
            "live": self.live,
            "depends_on": list(self.depends_on) if self.depends_on else None,
            "selector": self.selector,
        }


def parse_time(value: str) -> time:
    """`"07:30"` → time(7, 30)."""
    h, m = value.split(":")
    return time(int(h), int(m))


class SettingsRegistry:
    """All declared settings, in declaration order."""

    def __init__(self, settings: Iterable[Setting] = ()) -> None:
        self._settings: dict[str, Setting] = {}
        self.add(*settings)

    def add(self, *settings: Setting) -> None:
        for s in settings:
            if s.key in self._settings:
                raise ValueError(f"Setting {s.key} declared twice")
            self._settings[s.key] = s

    def __contains__(self, key: object) -> bool:
        return key in self._settings

    def __getitem__(self, key: str) -> Setting:
        try:
            return self._settings[key]
        except KeyError:
            raise SettingError(f"Unknown setting {key}") from None

    def __iter__(self):
        return iter(self._settings.values())

    def __len__(self) -> int:
        return len(self._settings)

    def sections(self) -> list[str]:
        return list(dict.fromkeys(s.section for s in self._settings.values()))

    def by_prefix(self, prefix: str) -> list[Setting]:
        return [s for k, s in self._settings.items() if k == prefix or k.startswith(f"{prefix}.")]

    def defaults(self) -> dict[str, Any]:
        return {k: s.default for k, s in self._settings.items()}

    def validate_mapping(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a whole mapping (import); unknown keys are an error."""
        return {k: self[k].validate(v) for k, v in values.items()}
