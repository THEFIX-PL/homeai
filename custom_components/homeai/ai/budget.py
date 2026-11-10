"""Cost ledger and budgets for AI calls.

Every call is counted per day and month and per tier. Budgets (`ai.budget_daily`, `ai.budget_monthly`, in the
currency of the prices, USD by default) either warn (persistent notification and journal) or block further
calls until the period ends (`ai.budget_mode`). Zero means no limit.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.ai_ledger"
KEEP_DAYS = 62


class Ledger:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.days: dict[str, dict[str, Any]] = {}  # YYYY-MM-DD → {"cost", "calls", "input", "output", "tiers": {...}}
        self._warned: set[str] = set()
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.days = dict(data.get("days") or {})
        self._warned = set(data.get("warned") or [])

    async def async_save(self) -> None:
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"days": self.days, "warned": sorted(self._warned)[-20:]}

    @callback
    def listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    @staticmethod
    def _today() -> str:
        return dt_util.now().date().isoformat()

    def today(self) -> float:
        return float(self.days.get(self._today(), {}).get("cost", 0.0))

    def month(self) -> float:
        prefix = self._today()[:7]
        return sum(float(d.get("cost", 0.0)) for day, d in self.days.items() if day.startswith(prefix))

    def calls_today(self) -> int:
        return int(self.days.get(self._today(), {}).get("calls", 0))

    def source_today(self, source: str) -> float:
        """Spent today through one connection (a tier subentry)."""
        return float(self.days.get(self._today(), {}).get("sources", {}).get(source, 0.0))

    def record(
        self,
        tier: str,
        model: str,
        cost: float,
        input_tokens: int,
        output_tokens: int,
        purpose: str,
        source: str | None = None,
    ) -> None:
        day = self.days.setdefault(self._today(), {"cost": 0.0, "calls": 0, "input": 0, "output": 0, "tiers": {}})
        if source:
            sources = day.setdefault("sources", {})
            sources[source] = round(sources.get(source, 0.0) + cost, 6)
        day["cost"] = round(day["cost"] + cost, 6)
        day["calls"] += 1
        day["input"] += input_tokens
        day["output"] += output_tokens
        t = day["tiers"].setdefault(tier, {"cost": 0.0, "calls": 0, "models": {}, "purposes": {}})
        t["cost"] = round(t["cost"] + cost, 6)
        t["calls"] += 1
        t["models"][model] = t["models"].get(model, 0) + 1
        t["purposes"][purpose] = t["purposes"].get(purpose, 0) + 1
        for old in sorted(self.days)[:-KEEP_DAYS]:
            del self.days[old]
        self._store.async_delay_save(self._data, 10)
        self._check()
        for cb in list(self._listeners):
            cb()

    # ——— Budgets ———
    def limits(self) -> list[tuple[str, float, float]]:
        """(period, spent, limit) for every period with a limit."""
        out = []
        daily = float(self.rt.settings.get("ai.budget_daily"))
        monthly = float(self.rt.settings.get("ai.budget_monthly"))
        if daily > 0:
            out.append(("day", self.today(), daily))
        if monthly > 0:
            out.append(("month", self.month(), monthly))
        return out

    def allowed(self) -> bool:
        if self.rt.settings.get("ai.budget_mode") != "block":
            return True
        return all(spent < limit for _period, spent, limit in self.limits())

    def _check(self) -> None:
        warn_at = int(self.rt.settings.get("ai.budget_warn_percent")) / 100
        for period, spent, limit in self.limits():
            key = f"{period}:{self._today() if period == 'day' else self._today()[:7]}"
            level = "over" if spent >= limit else ("warn" if spent >= limit * warn_at else None)
            if level is None or f"{key}:{level}" in self._warned:
                continue
            self._warned.add(f"{key}:{level}")
            text = self.rt.text(
                f"ai|budget_{level}",
                period=self.rt.text(f"ai|period_{period}"),
                spent=f"{spent:.2f}",
                limit=f"{limit:.2f}",
            )
            self.rt.journal.add("ai", text, result=level)
            persistent_notification.async_create(
                self.hass, text, title="HomeAI", notification_id=f"homeai_budget_{period}"
            )

    def summary(self) -> dict[str, Any]:
        return {
            "today": round(self.today(), 4),
            "month": round(self.month(), 4),
            "calls_today": self.calls_today(),
            "limits": [{"period": p, "spent": round(s, 4), "limit": lim} for p, s, lim in self.limits()],
            "allowed": self.allowed(),
        }
