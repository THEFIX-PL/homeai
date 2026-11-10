"""What leaves the house: names, rooms and states as allowed by the privacy level of each provider.

- minimal: people become “Person A”, rooms “Room A”; no calendar titles; device names kept generic.
- standard (default): names of devices, rooms and people; never private entities or areas, never secrets.
- full: everything above plus calendar titles.

Text from the home (names, states) is data, never instructions: it is cleaned and length-limited, and the
prompts tell the model so.
"""

from __future__ import annotations

import re
import string
from typing import Any

SECRET_ATTRIBUTES = frozenset(
    {"access_token", "token", "api_key", "password", "entity_picture", "stream_source", "code", "secret", "auth"}
)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
LEVELS = ("minimal", "standard", "full")


def clean(value: Any, limit: int = 120) -> str:
    text = CONTROL.sub(" ", str(value)).replace("<", "‹").replace(">", "›")
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Privacy:
    """One transformation for one request; keeps the pseudonym map so answers can be translated back."""

    def __init__(self, runtime: Any, level: str | None = None) -> None:
        self.rt = runtime
        self.level = level if level in LEVELS else str(runtime.settings.get("privacy.level"))
        self._aliases: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def _alias(self, kind: str, real: str) -> str:
        key = f"{kind}:{real}"
        if key not in self._aliases:
            n = self._counters.get(kind, 0)
            self._counters[kind] = n + 1
            label = string.ascii_uppercase[n % 26] + (str(n // 26) if n >= 26 else "")
            self._aliases[key] = f"{kind.title()} {label}"
        return self._aliases[key]

    def allowed(self, entity_id: str) -> bool:
        if self.level == "full":
            return entity_id not in self.rt.settings.get("privacy.never_send_entities")
        settings, world = self.rt.settings, self.rt.world
        if entity_id in settings.get("privacy.never_send_entities"):
            return False
        info = world.entity(entity_id)
        if info is None:
            return True
        if info.area_id and info.area_id in settings.get("privacy.never_send_areas"):
            return False
        return not world.has_label(entity_id, "label_private")

    def person(self, name: str) -> str:
        return self._alias("person", name) if self.level == "minimal" else clean(name, 60)

    def area(self, name: str) -> str:
        if not name:
            return ""
        return self._alias("room", name) if self.level == "minimal" else clean(name, 60)

    def entity_name(self, entity_id: str) -> str:
        name = self.rt.world.display_name(entity_id)
        if self.level == "minimal":
            return self._alias("device", name)
        return clean(name, 80)

    def calendar_title(self, title: str) -> str | None:
        return clean(title, 120) if self.level == "full" else None

    def attributes(self, attrs: dict[str, Any], keep: tuple[str, ...]) -> dict[str, Any]:
        return {k: clean(v, 60) for k, v in attrs.items() if k in keep and k not in SECRET_ATTRIBUTES}

    def restore(self, text: str) -> str:
        """Put real names back into a model's answer."""
        for key, alias in sorted(self._aliases.items(), key=lambda kv: -len(kv[1])):
            text = text.replace(alias, key.split(":", 1)[1])
        return text
