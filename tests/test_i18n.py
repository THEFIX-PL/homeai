"""Every setting and section has an English and a Polish label and description."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.homeai import i18n
from custom_components.homeai.settings import build_registry

I18N = Path(__file__).parents[1] / "custom_components" / "homeai" / "i18n"


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_settings_have_texts(lang: str) -> None:
    data = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
    registry = build_registry()
    missing = [s.key for s in registry if not (data["settings"].get(s.key) or {}).get("label")]
    assert not missing, f"missing labels in {lang}: {missing}"
    missing = [s.key for s in registry if not (data["settings"].get(s.key) or {}).get("description")]
    assert not missing, f"missing descriptions in {lang}: {missing}"
    for section in registry.sections():
        assert data["sections"][section]["label"]
    for s in registry:
        if s.options:
            labels = data["options"].get(s.key) or {}
            assert set(labels) >= set(s.options), f"{lang}: option labels for {s.key}"


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_same_keys_in_both_languages(lang: str) -> None:
    def keys(node: object, prefix: str = "") -> set[str]:
        if isinstance(node, dict):
            out: set[str] = set()
            for k, v in node.items():
                out |= keys(v, f"{prefix}{k}|")
            return out
        return {prefix}

    en = keys(json.loads((I18N / "en.json").read_text(encoding="utf-8")))
    pl = keys(json.loads((I18N / "pl.json").read_text(encoding="utf-8")))
    assert en == pl, f"differences: {sorted(en ^ pl)[:20]}"


def test_text_rendering_and_fallback() -> None:
    assert i18n.text("pl", "journal|setting_changed", key="x") == "Zmiana ustawienia: x"
    assert i18n.text("de", "journal|setting_changed", key="x") == "Setting changed: x"
    assert i18n.text("en", "nope|missing") == "missing"
    assert i18n.join("pl", ["a", "b", "c"]) == "a, b i c"
    assert i18n.text("en", "journal|setting_changed") == "Setting changed: {key}"


def test_ha_translations_cover_services_entities_and_exceptions() -> None:
    import json
    from pathlib import Path
    import re

    import yaml

    base = Path(__file__).parent.parent / "custom_components" / "homeai"
    services = yaml.safe_load((base / "services.yaml").read_text()) or {}
    code = "\n".join(p.read_text() for p in base.rglob("*.py"))
    used_exceptions = set(re.findall(r'translation_key="([a-z_]+)"', code))
    selector_keys = set(re.findall(r"translation_key: ([a-z_]+)", (base / "services.yaml").read_text()))
    icons = json.loads((base / "icons.json").read_text())
    en = json.loads((base / "translations" / "en.json").read_text())
    for lang in ("en", "pl"):
        tr = json.loads((base / "translations" / f"{lang}.json").read_text())
        for name, spec in services.items():
            assert tr["services"][name]["name"], (lang, name)
            for field in (spec or {}).get("fields", {}):
                assert tr["services"][name]["fields"][field]["name"], (lang, name, field)
            assert name in icons["services"], name
        for key in used_exceptions - {"not_loaded"} | {"not_loaded"}:
            if key in en.get("exceptions", {}):
                assert tr["exceptions"][key]["message"], (lang, key)
        for key in selector_keys:
            assert tr["selector"][key]["options"], (lang, key)
        assert set(tr["entity"]) == set(en["entity"])
        for platform, items in en["entity"].items():
            assert set(tr["entity"][platform]) == set(items), (lang, platform)
            for key in items:
                assert key in icons["entity"][platform], (platform, key)
