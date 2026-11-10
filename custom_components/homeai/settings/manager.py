"""Settings store: global values, scoped overrides, change history, listeners, export and import.

Values live in `.storage/homeai.settings`. Reading is synchronous and cheap (dict lookups), so any module can
ask for a value on every evaluation. Writing validates against the registry, records who changed what, saves
with a short delay and notifies listeners subscribed to a key or a key prefix.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN, LOGGER
from .registry import RESOLUTION_ORDER, Scope, Setting, SettingError, SettingsRegistry

STORAGE_KEY = f"{DOMAIN}.settings"
STORAGE_VERSION = 1
SAVE_DELAY = 2
HISTORY_LIMIT = 500


@dataclass(frozen=True, slots=True)
class Target:
    """What a value is resolved for. Any field may be missing; missing levels are skipped."""

    entity_id: str | None = None
    device_id: str | None = None
    area_id: str | None = None
    floor_id: str | None = None
    person_id: str | None = None

    def scope_keys(self) -> list[tuple[Scope, str]]:
        ids = {
            Scope.ENTITY: self.entity_id,
            Scope.DEVICE: self.device_id,
            Scope.AREA: self.area_id,
            Scope.FLOOR: self.floor_id,
            Scope.PERSON: self.person_id,
        }
        return [(s, f"{s}:{ids[s]}") for s in RESOLUTION_ORDER if s is not Scope.GLOBAL and ids.get(s)]


def scope_key(scope: Scope | str, ref: str | None = None) -> str:
    scope = Scope(scope)
    if scope is Scope.GLOBAL:
        return "global"
    if not ref:
        raise SettingError(f"{scope} override needs a reference")
    return f"{scope}:{ref}"


def parse_scope_key(key: str) -> tuple[Scope, str | None]:
    if key == "global":
        return Scope.GLOBAL, None
    scope, _, ref = key.partition(":")
    try:
        return Scope(scope), ref or None
    except ValueError:
        raise SettingError(f"Unknown scope {key}") from None


class SettingsManager:
    """Current values of every registered setting."""

    def __init__(self, hass: HomeAssistant, registry: SettingsRegistry) -> None:
        self.hass = hass
        self.registry = registry
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._global: dict[str, Any] = {}
        self._overrides: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._listeners: list[tuple[str, Callable[[str], None]]] = []

    # ——— Load and save ———
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._global = self._clean(data.get("global") or {}, Scope.GLOBAL)
        self._overrides = {}
        for skey, values in (data.get("overrides") or {}).items():
            try:
                scope, _ref = parse_scope_key(skey)
            except SettingError:
                continue
            clean = self._clean(values or {}, scope)
            if clean:
                self._overrides[skey] = clean
        self._history = list(data.get("history") or [])[-HISTORY_LIMIT:]

    def _clean(self, values: dict[str, Any], scope: Scope) -> dict[str, Any]:
        """Drop values for settings that no longer exist or no longer validate (after an upgrade)."""
        clean: dict[str, Any] = {}
        for key, value in values.items():
            if key not in self.registry:
                continue
            setting = self.registry[key]
            if scope not in setting.scopes:
                continue
            try:
                clean[key] = setting.validate(value)
            except SettingError as err:
                LOGGER.warning("Ignoring stored value for %s: %s", key, err)
        return clean

    def _data(self) -> dict[str, Any]:
        return {"global": self._global, "overrides": self._overrides, "history": self._history}

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def async_flush(self) -> None:
        await self._store.async_save(self._data())

    # ——— Reading ———
    def get(self, key: str, target: Target | None = None) -> Any:
        """Effective value of `key` for `target` (or the global value)."""
        setting = self.registry[key]
        if target is not None:
            for scope, skey in target.scope_keys():
                if scope in setting.scopes and key in (values := self._overrides.get(skey, {})):
                    return values[key]
        return self._global.get(key, setting.default)

    def source(self, key: str, target: Target | None = None) -> str:
        """Where the effective value comes from: a scope key, `global` or `default`."""
        setting = self.registry[key]
        if target is not None:
            for scope, skey in target.scope_keys():
                if scope in setting.scopes and key in self._overrides.get(skey, {}):
                    return skey
        return "global" if key in self._global else "default"

    def overrides_for(self, skey: str) -> dict[str, Any]:
        return dict(self._overrides.get(skey, {}))

    def overrides_of(self, key: str) -> dict[str, Any]:
        """All scoped overrides of one setting: scope key → value."""
        return {skey: values[key] for skey, values in self._overrides.items() if key in values}

    def all_global(self) -> dict[str, Any]:
        return {s.key: self._global.get(s.key, s.default) for s in self.registry}

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(reversed(self._history[-limit:]))

    # ——— Writing ———
    def needs_confirmation(self, key: str, value: Any, skey: str = "global") -> bool:
        setting = self.registry[key]
        new = setting.validate(value)
        old = self._overrides.get(skey, {}).get(key, self.get(key)) if skey != "global" else self.get(key)
        return setting.lowers_protection(old, new)

    @callback
    def set(
        self,
        key: str,
        value: Any,
        *,
        skey: str = "global",
        user: str | None = None,
        confirmed: bool = False,
        is_admin: bool = True,
    ) -> Any:
        """Validate and store a value. Raises SettingError (unknown key, bad value, scope, permission)."""
        setting = self.registry[key]
        scope, _ref = parse_scope_key(skey)
        if scope not in setting.scopes:
            raise SettingError(f"{key} cannot be overridden per {scope}")
        if setting.admin_only and not is_admin:
            raise SettingError(f"{key} can only be changed by an administrator")
        new = setting.validate(value)
        old = self.get(key) if skey == "global" else self._overrides.get(skey, {}).get(key, self.get(key))
        if setting.lowers_protection(old, new) and not confirmed:
            raise SettingError(f"{key}: this change lowers protection and needs confirmation")
        if skey == "global":
            if new == setting.default:
                self._global.pop(key, None)
            else:
                self._global[key] = new
        else:
            self._overrides.setdefault(skey, {})[key] = new
        self._record(key, skey, old, new, user)
        self._notify(key)
        return new

    @callback
    def reset(self, key: str, *, skey: str = "global", user: str | None = None, is_admin: bool = True) -> None:
        """Remove a value: global → default, override → inherit."""
        setting = self.registry[key]
        if setting.admin_only and not is_admin:
            raise SettingError(f"{key} can only be changed by an administrator")
        if skey == "global":
            if key not in self._global:
                return
            old = self._global.pop(key)
        else:
            values = self._overrides.get(skey, {})
            if key not in values:
                return
            old = values.pop(key)
            if not values:
                self._overrides.pop(skey, None)
        self._record(key, skey, old, None, user, reset=True)
        self._notify(key)

    @callback
    def reset_section(self, section: str, *, user: str | None = None, is_admin: bool = True) -> int:
        """Reset all global values of a section to defaults; overrides stay."""
        count = 0
        for setting in self.registry:
            if setting.section == section and setting.key in self._global:
                self.reset(setting.key, user=user, is_admin=is_admin)
                count += 1
        return count

    @callback
    def undo_last(self, *, user: str | None = None, is_admin: bool = True) -> dict[str, Any] | None:
        """Restore the value from before the most recent change."""
        if not self._history:
            return None
        last = self._history[-1]
        key, skey = last["key"], last["scope"]
        if key not in self.registry:
            return None
        if last["old"] is None or (skey == "global" and last["old"] == self.registry[key].default):
            self.reset(key, skey=skey, user=user, is_admin=is_admin)
        else:
            self.set(key, last["old"], skey=skey, user=user, confirmed=True, is_admin=is_admin)
        return last

    def _record(self, key: str, skey: str, old: Any, new: Any, user: str | None, *, reset: bool = False) -> None:
        self._history.append(
            {
                "ts": dt_util.utcnow().isoformat(timespec="seconds"),
                "key": key,
                "scope": skey,
                "old": old,
                "new": new,
                "reset": reset,
                "user": user,
            }
        )
        del self._history[:-HISTORY_LIMIT]
        self._save()

    # ——— Export and import ———
    def export(self) -> dict[str, Any]:
        """Everything the user changed (no defaults, no history). Secrets never live here."""
        return {"version": STORAGE_VERSION, "global": dict(self._global), "overrides": dict(self._overrides)}

    @callback
    def import_(self, data: dict[str, Any], *, user: str | None = None) -> int:
        """Replace all values with an export. Validates everything first: all or nothing."""
        if not isinstance(data, dict):
            raise SettingError("Import: expected an object")
        new_global = self.registry.validate_mapping(data.get("global") or {})
        new_overrides: dict[str, dict[str, Any]] = {}
        for skey, values in (data.get("overrides") or {}).items():
            scope, _ref = parse_scope_key(skey)
            checked = self.registry.validate_mapping(values or {})
            for key in checked:
                if scope not in self.registry[key].scopes:
                    raise SettingError(f"{key} cannot be overridden per {scope}")
            if checked:
                new_overrides[skey] = checked
        changed = set(self._global) | set(new_global)
        for values in (*self._overrides.values(), *new_overrides.values()):
            changed |= set(values)
        self._global, self._overrides = new_global, new_overrides
        self._record("import", "global", None, None, user)
        for key in changed:
            self._notify(key)
        return len(changed)

    # ——— Listeners ———
    @callback
    def listen(self, prefix: str, cb: Callable[[str], None]) -> Callable[[], None]:
        """Call `cb(key)` whenever a setting equal to or under `prefix` changes."""
        entry = (prefix, cb)
        self._listeners.append(entry)

        def remove() -> None:
            if entry in self._listeners:
                self._listeners.remove(entry)

        return remove

    def _notify(self, key: str) -> None:
        for prefix, cb in list(self._listeners):
            if key == prefix or key.startswith(f"{prefix}.") or prefix == "":
                try:
                    cb(key)
                except Exception:
                    LOGGER.exception("Settings listener for %s failed", prefix)

    def keys_with_prefix(self, prefix: str) -> Iterable[Setting]:
        return self.registry.by_prefix(prefix)
