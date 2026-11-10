"""HomeAI settings: declarations, storage and resolution."""

from .definitions import build_registry
from .manager import SettingsManager, Target, parse_scope_key, scope_key
from .registry import Scope, Setting, SettingError, SettingsRegistry, SettingType, parse_time

__all__ = [
    "Scope",
    "Setting",
    "SettingError",
    "SettingType",
    "SettingsManager",
    "SettingsRegistry",
    "Target",
    "build_registry",
    "parse_scope_key",
    "parse_time",
    "scope_key",
]
