"""Modules started after the world model, in data-flow order. Each entry: (name, factory(runtime))."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

STAGES: list[tuple[str, Callable[[Any], Any]]] = []
