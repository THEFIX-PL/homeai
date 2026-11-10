"""HomeAI's own texts: settings labels, situation texts, notification texts (en, pl).

Home Assistant's `translations/` only covers fixed categories (config flow, entities, services…). Texts that
HomeAI generates itself — situation titles in pushes, setting labels in the panel — live in `i18n/<lang>.json`
and are rendered here. English is the fallback for any missing key.
"""

from __future__ import annotations

import json
from pathlib import Path
import string
from typing import Any

from homeassistant.core import HomeAssistant

SUPPORTED = ("en", "pl")
FALLBACK = "en"
_DIR = Path(__file__).parent / "i18n"
_CACHE: dict[str, dict[str, Any]] = {}


def _load(lang: str) -> dict[str, Any]:
    if lang not in _CACHE:
        path = _DIR / f"{lang}.json"
        _CACHE[lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _CACHE[lang]


async def async_preload(hass: HomeAssistant) -> None:
    """Read all language files once, outside the event loop."""
    await hass.async_add_executor_job(lambda: [_load(lang) for lang in SUPPORTED])


def resolve_language(hass: HomeAssistant, configured: str = "auto") -> str:
    if configured in SUPPORTED:
        return configured
    lang = (hass.config.language or FALLBACK).split("-")[0].lower()
    return lang if lang in SUPPORTED else FALLBACK


def _lookup(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("|"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def text(lang: str, path: str, **placeholders: Any) -> str:
    """Rendered text at `path` (segments separated by `|`, so keys may contain dots)."""
    value = _lookup(_load(lang), path)
    if not isinstance(value, str):
        value = _lookup(_load(FALLBACK), path)
    if not isinstance(value, str):
        return path.rsplit("|", 1)[-1]
    if not placeholders:
        return value
    return string.Formatter().vformat(value, (), _SafeDict({k: _fmt(v, lang) for k, v in placeholders.items()}))


def has(lang: str, path: str) -> bool:
    return isinstance(_lookup(_load(lang), path), str)


def section(lang: str, path: str) -> dict[str, Any]:
    value = _lookup(_load(lang), path)
    fallback = _lookup(_load(FALLBACK), path)
    merged: dict[str, Any] = dict(fallback) if isinstance(fallback, dict) else {}
    if isinstance(value, dict):
        merged.update(value)
    return merged


def join(lang: str, items: list[str]) -> str:
    """“a, b and c” in the given language."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    conj = text(lang, "common|and")
    return f"{', '.join(items[:-1])} {conj} {items[-1]}"


def _fmt(value: Any, lang: str) -> str:
    if isinstance(value, float):
        s = f"{value:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") if lang == "pl" else s
    if isinstance(value, (list, tuple)):
        return join(lang, [_fmt(v, lang) for v in value])
    return str(value)
