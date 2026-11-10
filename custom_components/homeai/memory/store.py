"""Facts and preferences.

A fact has a scope (home, person:<id>, area:<id>, device:<id>, entity:<id>), a source (person, ai, learning), a
confidence and an optional expiry. What people say is approved at once; what HomeAI learns is only a proposal
until someone approves it. Retrieval is by scope and words; no vector database is needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, LOGGER

STORAGE_KEY = f"{DOMAIN}.memory"
MAX_FACTS = 1000
SOURCES = ("person", "ai", "learning")


class Memory:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.facts: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[], None]] = []

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.facts = {f["id"]: f for f in data.get("facts", []) if isinstance(f, dict) and "id" in f}
        self._prune()

    async def async_unload(self) -> None:
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"facts": list(self.facts.values())}

    @callback
    def listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _changed(self) -> None:
        self._store.async_delay_save(self._data, 5)
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                LOGGER.exception("Memory listener failed")

    def _prune(self) -> None:
        now = dt_util.utcnow()
        for fid, fact in list(self.facts.items()):
            expires = dt_util.parse_datetime(fact["expires"]) if fact.get("expires") else None
            if expires is not None and expires <= now:
                del self.facts[fid]
        while len(self.facts) > MAX_FACTS:  # forget the least confident, oldest first
            worst = min(self.facts.values(), key=lambda f: (f.get("approved", False), f["confidence"], f["created"]))
            del self.facts[worst["id"]]

    def add(
        self,
        text: str,
        *,
        scope: str = "home",
        source: str = "person",
        confidence: float = 1.0,
        expires: str | None = None,
        author: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = " ".join(str(text).split())[:500]
        for fact in self.facts.values():  # the same thing said again refreshes it
            if fact["scope"] == scope and fact["text"].lower() == text.lower():
                fact["confidence"] = max(fact["confidence"], confidence)
                fact["updated"] = dt_util.utcnow().isoformat(timespec="seconds")
                self._changed()
                return fact
        fact = {
            "id": ulid_util.ulid_now().lower(),
            "text": text,
            "scope": scope,
            "source": source if source in SOURCES else "ai",
            "confidence": max(0.0, min(1.0, confidence)),
            "approved": source == "person",
            "created": dt_util.utcnow().isoformat(timespec="seconds"),
            "expires": expires,
            "author": author,
            "data": data or {},
        }
        self.facts[fact["id"]] = fact
        self._prune()
        self._changed()
        return fact

    def approve(self, fact_id: str) -> bool:
        fact = self.facts.get(fact_id)
        if fact is None:
            return False
        fact["approved"] = True
        self._changed()
        return True

    def remove(self, fact_id: str) -> bool:
        if self.facts.pop(fact_id, None) is None:
            return False
        self._changed()
        return True

    def search(
        self, words: str = "", *, scopes: list[str] | None = None, limit: int = 10, approved_only: bool = True
    ) -> list[dict[str, Any]]:
        terms = [w for w in words.lower().split() if len(w) > 2]
        out = []
        for fact in self.facts.values():
            if approved_only and not fact.get("approved"):
                continue
            if scopes and fact["scope"] not in scopes and fact["scope"] != "home":
                continue
            score = sum(1 for t in terms if t in fact["text"].lower()) if terms else 1
            if terms and not score:
                continue
            out.append((score, fact["confidence"], fact["created"], fact))
        out.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return [x[3] for x in out[:limit]]
