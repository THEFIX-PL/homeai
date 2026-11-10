"""Settings registry and manager: validation, scopes, inheritance, history, import/export, listeners."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.homeai.settings import (
    Scope,
    Setting,
    SettingError,
    SettingsManager,
    SettingsRegistry,
    SettingType,
    Target,
    build_registry,
)


def test_every_default_is_valid_and_keys_unique() -> None:
    registry = build_registry()
    assert len(registry) > 30
    for setting in registry:
        assert setting.validate(setting.default) == setting.default or setting.type in (
            SettingType.STRINGS,
            SettingType.ENTITIES,
            SettingType.MULTISELECT,
        )


@pytest.mark.parametrize(
    ("setting", "good", "bad"),
    [
        (Setting("a.b", SettingType.INT, 5, "x", min=1, max=10), 7, 11),
        (Setting("a.c", SettingType.FLOAT, 1.5, "x", min=0), 0.0, -1),
        (Setting("a.d", SettingType.BOOL, True, "x"), False, "yes"),
        (Setting("a.e", SettingType.SELECT, "x", "x", options=("x", "y")), "y", "z"),
        (Setting("a.f", SettingType.TIME, "07:00", "x"), "23:59", "24:00"),
        (Setting("a.g", SettingType.ENTITIES, [], "x"), ["light.a"], ["nope"]),
        (Setting("a.h", SettingType.MULTISELECT, [], "x", options=("p", "q")), ["q"], ["r"]),
    ],
)
def test_validation(setting: Setting, good: object, bad: object) -> None:
    setting.validate(good)
    with pytest.raises(SettingError):
        setting.validate(bad)


def test_bad_declarations_rejected() -> None:
    with pytest.raises(ValueError):
        Setting("nodot", SettingType.INT, 1, "x")
    with pytest.raises(ValueError):
        Setting("a.b", SettingType.INT, 1, "x", scopes=frozenset({Scope.AREA}))
    with pytest.raises(SettingError):
        Setting("a.b", SettingType.INT, 50, "x", max=10)


def _registry() -> SettingsRegistry:
    return SettingsRegistry(
        [
            Setting(
                "t.threshold",
                SettingType.INT,
                20,
                "t",
                min=0,
                max=100,
                scopes=frozenset({Scope.GLOBAL, Scope.AREA, Scope.DEVICE, Scope.ENTITY}),
            ),
            Setting("t.safety", SettingType.BOOL, True, "t", confirm="disable"),
            Setting("t.member", SettingType.STRING, "x", "t", admin_only=False),
            Setting(
                "t.role",
                SettingType.SELECT,
                "member",
                "t",
                options=("member", "admin"),
                scopes=frozenset({Scope.GLOBAL, Scope.PERSON}),
            ),
        ]
    )


async def test_inheritance_order(hass: HomeAssistant) -> None:
    m = SettingsManager(hass, _registry())
    await m.async_load()
    target = Target(entity_id="sensor.a", device_id="dev1", area_id="kitchen")
    assert m.get("t.threshold", target) == 20
    assert m.source("t.threshold", target) == "default"
    m.set("t.threshold", 30)
    assert m.get("t.threshold", target) == 30
    m.set("t.threshold", 40, skey="area:kitchen")
    assert m.get("t.threshold", target) == 40
    assert m.get("t.threshold", Target(entity_id="sensor.b", area_id="hall")) == 30
    m.set("t.threshold", 50, skey="device:dev1")
    m.set("t.threshold", 60, skey="entity:sensor.a")
    assert m.get("t.threshold", target) == 60
    assert m.source("t.threshold", target) == "entity:sensor.a"
    m.reset("t.threshold", skey="entity:sensor.a")
    assert m.get("t.threshold", target) == 50
    assert m.overrides_of("t.threshold") == {"area:kitchen": 40, "device:dev1": 50}


async def test_scope_permission_and_confirmation(hass: HomeAssistant) -> None:
    m = SettingsManager(hass, _registry())
    await m.async_load()
    with pytest.raises(SettingError, match="cannot be overridden"):
        m.set("t.safety", False, skey="area:kitchen")
    with pytest.raises(SettingError, match="administrator"):
        m.set("t.threshold", 10, is_admin=False)
    m.set("t.member", "y", is_admin=False)
    assert m.needs_confirmation("t.safety", False)
    with pytest.raises(SettingError, match="confirmation"):
        m.set("t.safety", False)
    m.set("t.safety", False, confirmed=True)
    assert m.get("t.safety") is False
    assert not m.needs_confirmation("t.safety", True)


async def test_history_undo_persist_and_import(hass: HomeAssistant) -> None:
    m = SettingsManager(hass, _registry())
    await m.async_load()
    m.set("t.threshold", 33, user="Łukasz")
    m.set("t.role", "admin", skey="person:person.a")
    assert m.history()[0]["key"] == "t.role"
    m.undo_last()
    assert m.get("t.role", Target(person_id="person.a")) == "member"
    exported = m.export()
    await m.async_flush()

    m2 = SettingsManager(hass, _registry())
    await m2.async_load()
    assert m2.get("t.threshold") == 33

    with pytest.raises(SettingError):
        m2.import_({"global": {"t.threshold": 500}})
    assert m2.get("t.threshold") == 33  # nothing changed
    changed = m2.import_({"global": {}, "overrides": {"area:x": {"t.threshold": 1}}})
    assert changed >= 1
    assert m2.get("t.threshold") == 20
    assert m2.get("t.threshold", Target(area_id="x")) == 1
    m2.import_(exported)
    assert m2.get("t.threshold") == 33


async def test_setting_equal_to_default_is_not_stored(hass: HomeAssistant) -> None:
    m = SettingsManager(hass, _registry())
    await m.async_load()
    m.set("t.threshold", 20)
    assert m.export()["global"] == {}


async def test_listeners(hass: HomeAssistant) -> None:
    m = SettingsManager(hass, _registry())
    await m.async_load()
    seen: list[str] = []
    remove = m.listen("t", seen.append)
    m.set("t.threshold", 21)
    m.reset("t.threshold")
    remove()
    m.set("t.threshold", 22)
    assert seen == ["t.threshold", "t.threshold"]
