"""World model: rooms, devices, entities, people and what each entity is for — kept up to date incrementally.

Built once from Home Assistant's registries, then updated per entity or per device as registry events and new
entities arrive. Detectors read indexes (`with_role`, `in_area`, `of_device`) instead of scanning registries,
so evaluating the whole home stays cheap even with thousands of entities.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.helpers.debounce import Debouncer

from ..const import DOMAIN, LOGGER
from ..settings import SettingsManager, Target
from .roles import Role, classify

LABEL_SETTINGS = ("label_ignore", "label_personal", "label_critical", "label_protective", "label_private")


@dataclass(slots=True)
class EntityInfo:
    entity_id: str
    domain: str
    name: str
    device_id: str | None
    area_id: str | None
    floor_id: str | None
    labels: frozenset[str]
    device_class: str | None
    unit: str | None
    platform: str | None
    config_entry_id: str | None
    category: str | None  # "config" / "diagnostic" / None
    translation_key: str | None
    hidden: bool
    roles: frozenset[Role]

    @property
    def target(self) -> Target:
        return Target(entity_id=self.entity_id, device_id=self.device_id, area_id=self.area_id, floor_id=self.floor_id)


@dataclass(slots=True)
class DeviceInfo:
    device_id: str
    name: str
    area_id: str | None
    labels: frozenset[str]
    config_entry_id: str | None
    identifiers: frozenset[tuple[str, str]]
    manufacturer: str | None
    model: str | None
    via_device_id: str | None
    entities: set[str] = field(default_factory=set)


@dataclass(slots=True)
class AreaInfo:
    area_id: str
    name: str
    floor_id: str | None
    temperature_entity_id: str | None
    humidity_entity_id: str | None


@dataclass(slots=True)
class FloorInfo:
    floor_id: str
    name: str
    level: int | None


@dataclass(slots=True)
class PersonInfo:
    entity_id: str
    name: str
    user_id: str | None
    device_trackers: tuple[str, ...]
    state: str

    @property
    def home(self) -> bool:
        return self.state == "home"


class WorldModel:
    """Live picture of the home built from Home Assistant's registries."""

    def __init__(self, hass: HomeAssistant, settings: SettingsManager) -> None:
        self.hass = hass
        self.settings = settings
        self.entities: dict[str, EntityInfo] = {}
        self.devices: dict[str, DeviceInfo] = {}
        self.areas: dict[str, AreaInfo] = {}
        self.floors: dict[str, FloorInfo] = {}
        self.persons: dict[str, PersonInfo] = {}
        self._by_role: dict[Role, set[str]] = defaultdict(set)
        self._by_area: dict[str | None, set[str]] = defaultdict(set)
        self._by_entry: dict[str, set[str]] = defaultdict(set)
        self._listeners: list[Callable[[str, set[str]], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._full = Debouncer(hass, LOGGER, cooldown=2.0, immediate=False, function=self._rebuild_and_notify)

    # ——— Lifecycle ———
    async def async_start(self) -> None:
        if self.settings.get("world.create_labels"):
            self._ensure_labels()
        self.rebuild()
        bus = self.hass.bus
        self._unsubs += [
            bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_entity_registry),
            bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, self._on_device_registry),
            bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, self._on_structure),
            bus.async_listen(fr.EVENT_FLOOR_REGISTRY_UPDATED, self._on_structure),
            bus.async_listen(lr.EVENT_LABEL_REGISTRY_UPDATED, self._on_structure),
            bus.async_listen(EVENT_STATE_CHANGED, self._on_state),
            self.settings.listen("world", lambda _k: self.hass.async_create_task(self._full.async_call())),
        ]

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._full.async_cancel()

    @callback
    def listen(self, cb: Callable[[str, set[str]], None]) -> Callable[[], None]:
        """`cb(kind, entity_ids)` after changes; kind is "rebuild", "entity" or "person"."""
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _notify(self, kind: str, ids: set[str]) -> None:
        for cb in list(self._listeners):
            try:
                cb(kind, ids)
            except Exception:
                LOGGER.exception("World model listener failed")

    # ——— Labels HomeAI understands ———
    def label(self, which: str) -> str:
        return str(self.settings.get(f"world.{which}"))

    def _ensure_labels(self) -> None:
        reg = lr.async_get(self.hass)
        names = {
            "label_ignore": ("HomeAI: ignore", "mdi:eye-off-outline"),
            "label_personal": ("HomeAI: personal", "mdi:account-outline"),
            "label_critical": ("HomeAI: critical", "mdi:alert-octagon-outline"),
            "label_protective": ("HomeAI: protective action", "mdi:shield-check-outline"),
            "label_private": ("HomeAI: private", "mdi:incognito"),
        }
        for which, (name, icon) in names.items():
            label_id = self.label(which)
            if reg.async_get_label(label_id) is None and reg.async_get_label_by_name(name) is None:
                try:
                    reg.async_create(name, icon=icon)
                except ValueError:
                    LOGGER.debug("Label %s already exists", name)

    # ——— Building ———
    def rebuild(self) -> None:
        """Build everything from scratch (startup, area/floor/label changes, settings changes)."""
        self.floors = {
            f.floor_id: FloorInfo(f.floor_id, f.name, f.level) for f in fr.async_get(self.hass).async_list_floors()
        }
        self.areas = {
            a.id: AreaInfo(a.id, a.name, a.floor_id, a.temperature_entity_id, a.humidity_entity_id)
            for a in ar.async_get(self.hass).async_list_areas()
        }
        self.devices = {}
        for d in dr.async_get(self.hass).devices:  # iterating yields device entries
            if not d.disabled_by and not _own(d):
                self.devices[d.id] = self._device_info(d)
        self.entities.clear()
        self._by_role.clear()
        self._by_area.clear()
        self._by_entry.clear()
        registry = er.async_get(self.hass)
        seen: set[str] = set()
        for entry in registry.entities.values():
            seen.add(entry.entity_id)
            self._add(entry.entity_id, entry, self.hass.states.get(entry.entity_id))
        for state in self.hass.states.async_all():
            if state.entity_id not in seen:
                self._add(state.entity_id, None, state)
        self._rebuild_persons()

    async def _rebuild_and_notify(self) -> None:
        self.rebuild()
        self._notify("rebuild", set(self.entities))

    def _device_info(self, d: dr.DeviceEntry) -> DeviceInfo:
        return DeviceInfo(
            device_id=d.id,
            name=d.name_by_user or d.name or "",
            area_id=d.area_id,
            labels=frozenset(d.labels),
            config_entry_id=d.config_entry_id,
            identifiers=frozenset(d.identifiers),
            manufacturer=d.manufacturer,
            model=d.model,
            via_device_id=d.via_device_id,
        )

    def _included(
        self, entity_id: str, entry: er.RegistryEntry | None, area_id: str | None, labels: frozenset[str]
    ) -> bool:
        if entry is not None:
            if entry.disabled_by or entry.platform == DOMAIN:  # never watch our own entities
                return False
            if entry.hidden_by and not self.settings.get("world.include_hidden"):
                return False
        if self.label("label_ignore") in labels:
            return False
        if any(fnmatchcase(entity_id, p) for p in self.settings.get("world.exclude_entities")):
            return False
        domain = entity_id.split(".", 1)[0]
        if (domains := self.settings.get("world.include_domains")) and domain not in domains and domain != "person":
            return False
        scope = self.settings.get("world.scope")
        if scope == "selected" and domain != "person":
            return area_id in set(self.settings.get("world.include_areas"))
        if scope == "exposed" and domain != "person":
            from homeassistant.components.homeassistant.exposed_entities import (
                async_should_expose,
            )

            return async_should_expose(self.hass, "conversation", entity_id)
        return True

    def _add(self, entity_id: str, entry: er.RegistryEntry | None, state: State | None) -> EntityInfo | None:
        domain = entity_id.split(".", 1)[0]
        device = self.devices.get(entry.device_id) if entry and entry.device_id else None
        area_id = (entry.area_id if entry else None) or (device.area_id if device else None)
        labels = frozenset(entry.labels if entry else ()) | (device.labels if device else frozenset())
        if not self._included(entity_id, entry, area_id, labels):
            return None
        attrs = state.attributes if state else {}
        device_class = (entry.device_class or entry.original_device_class) if entry else None
        info = EntityInfo(
            entity_id=entity_id,
            domain=domain,
            name=self._entity_name(entry, state, device),
            device_id=device.device_id if device else None,
            area_id=area_id,
            floor_id=self.areas[area_id].floor_id if area_id in self.areas else None,
            labels=labels,
            device_class=device_class or attrs.get("device_class"),
            unit=(entry.unit_of_measurement if entry else None) or attrs.get("unit_of_measurement"),
            platform=entry.platform if entry else None,
            config_entry_id=entry.config_entry_id if entry else None,
            category=str(entry.entity_category) if entry and entry.entity_category else None,
            translation_key=entry.translation_key if entry else None,
            hidden=bool(entry and entry.hidden_by),
            roles=classify(
                domain,
                attrs,
                device_class=device_class,
                translation_key=entry.translation_key if entry else None,
                entity_id=entity_id,
            ),
        )
        self.entities[entity_id] = info
        for role in info.roles:
            self._by_role[role].add(entity_id)
        self._by_area[info.area_id].add(entity_id)
        if info.config_entry_id:
            self._by_entry[info.config_entry_id].add(entity_id)
        if device:
            device.entities.add(entity_id)
        return info

    def _remove(self, entity_id: str) -> None:
        info = self.entities.pop(entity_id, None)
        if info is None:
            return
        for role in info.roles:
            self._by_role[role].discard(entity_id)
        self._by_area[info.area_id].discard(entity_id)
        if info.config_entry_id:
            self._by_entry[info.config_entry_id].discard(entity_id)
        if info.device_id and (device := self.devices.get(info.device_id)):
            device.entities.discard(entity_id)

    def _refresh_entity(self, entity_id: str) -> None:
        self._remove(entity_id)
        entry = er.async_get(self.hass).async_get(entity_id)
        state = self.hass.states.get(entity_id)
        if entry is not None or state is not None:
            self._add(entity_id, entry, state)

    @staticmethod
    def _entity_name(entry: er.RegistryEntry | None, state: State | None, device: DeviceInfo | None) -> str:
        if state is not None and state.name:
            return state.name
        if entry is not None:
            name = entry.name or entry.original_name
            if name and device and device.name and entry.has_entity_name:
                return f"{device.name} {name}"
            return name or (device.name if device else "") or entry.entity_id
        return ""

    def _rebuild_persons(self) -> None:
        self.persons = {}
        for state in self.hass.states.async_all("person"):
            self.persons[state.entity_id] = PersonInfo(
                entity_id=state.entity_id,
                name=state.name,
                user_id=state.attributes.get("user_id"),
                device_trackers=tuple(state.attributes.get("device_trackers") or ()),
                state=state.state,
            )

    # ——— Events ———
    @callback
    def _on_entity_registry(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if not entity_id:
            return
        if event.data.get("action") == "remove":
            self._remove(entity_id)
        else:
            self._refresh_entity(entity_id)
            if old := (event.data.get("old_entity_id")):
                self._remove(old)
        self._notify("entity", {entity_id})

    @callback
    def _on_device_registry(self, event: Event) -> None:
        device_id = event.data.get("device_id")
        if not device_id:
            return
        old_entities = set(self.devices[device_id].entities) if device_id in self.devices else set()
        d = dr.async_get(self.hass).async_get(device_id)
        if d is None or d.disabled_by or _own(d) or event.data.get("action") == "remove":
            self.devices.pop(device_id, None)
        else:
            self.devices[device_id] = self._device_info(d)
        ids = old_entities | {e.entity_id for e in er.async_entries_for_device(er.async_get(self.hass), device_id)}
        for entity_id in ids:
            self._refresh_entity(entity_id)
        self._notify("entity", ids)

    @callback
    def _on_structure(self, _event: Event) -> None:
        self.hass.async_create_task(self._full.async_call())

    @callback
    def _on_state(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        old: State | None = event.data.get("old_state")
        new: State | None = event.data.get("new_state")
        if entity_id.startswith("person."):
            if new is None:
                self.persons.pop(entity_id, None)
            else:
                self.persons[entity_id] = PersonInfo(
                    entity_id=entity_id,
                    name=new.name,
                    user_id=new.attributes.get("user_id"),
                    device_trackers=tuple(new.attributes.get("device_trackers") or ()),
                    state=new.state,
                )
            self._notify("person", {entity_id})
        if (
            old is None
            or new is None
            or old.attributes.get("device_class") != new.attributes.get("device_class")
            or old.attributes.get("unit_of_measurement") != new.attributes.get("unit_of_measurement")
        ):
            self._refresh_entity(entity_id)
            self._notify("entity", {entity_id})

    # ——— Queries ———
    def entity(self, entity_id: str) -> EntityInfo | None:
        return self.entities.get(entity_id)

    def with_role(self, *roles: Role) -> set[str]:
        out: set[str] = set()
        for role in roles:
            out |= self._by_role.get(role, set())
        return out

    def in_area(self, area_id: str | None) -> set[str]:
        return set(self._by_area.get(area_id, set()))

    def of_entry(self, entry_id: str) -> set[str]:
        return set(self._by_entry.get(entry_id, set()))

    def of_device(self, device_id: str) -> set[str]:
        device = self.devices.get(device_id)
        return set(device.entities) if device else set()

    def has_label(self, entity_id: str, which: str) -> bool:
        info = self.entities.get(entity_id)
        return bool(info and self.label(which) in info.labels)

    def device_has_label(self, device_id: str, which: str) -> bool:
        device = self.devices.get(device_id)
        return bool(device and self.label(which) in device.labels)

    def area_name(self, area_id: str | None) -> str:
        return self.areas[area_id].name if area_id in self.areas else ""

    def device_name(self, device_id: str | None) -> str:
        return self.devices[device_id].name if device_id in self.devices else ""

    def display_name(self, entity_id: str) -> str:
        info = self.entities.get(entity_id)
        if info and info.name:
            return info.name
        state = self.hass.states.get(entity_id)
        return state.name if state else entity_id

    def state(self, entity_id: str) -> State | None:
        return self.hass.states.get(entity_id)

    def value(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            v = float(state.state)
        except TypeError, ValueError:
            return None
        return v if v == v and v not in (float("inf"), float("-inf")) else None

    def target(self, entity_id: str) -> Target:
        info = self.entities.get(entity_id)
        return info.target if info else Target(entity_id=entity_id)

    def ids(self, roles: Iterable[Role] = ()) -> set[str]:
        roles = tuple(roles)
        return self.with_role(*roles) if roles else set(self.entities)

    def summary(self) -> dict[str, Any]:
        """Counts for diagnostics and the panel."""
        return {
            "entities": len(self.entities),
            "devices": len(self.devices),
            "areas": len(self.areas),
            "floors": len(self.floors),
            "persons": len(self.persons),
            "roles": {str(r): len(ids) for r, ids in sorted(self._by_role.items()) if ids},
        }


def _own(d: dr.DeviceEntry) -> bool:
    """HomeAI's own service device is not part of the home it watches."""
    return any(domain == DOMAIN for domain, _ in d.identifiers)
