"""Entities contributed by later stages, by platform (each stage appends a factory)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

FACTORIES: dict[str, list[Callable[[Any], list[Any]]]] = {}


def register(platform: str, factory: Callable[[Any], list[Any]]) -> None:
    FACTORIES.setdefault(platform, []).append(factory)


def extra_entities(rt: Any, platform: str) -> list[Any]:
    out: list[Any] = []
    for factory in FACTORIES.get(platform, []):
        try:
            out += factory(rt)
        except Exception:
            from .const import LOGGER

            LOGGER.exception("Extra %s entities failed", platform)
    return out
