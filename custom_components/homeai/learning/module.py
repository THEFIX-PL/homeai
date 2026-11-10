"""The learning stage: norms and anomalies, habit proposals, feedback from people, and the weekly review.

Learned things never act by themselves: habits become proposals a person approves; repeated undo of an
automatic action turns that action back to “propose”; repeated refusals keep HomeAI from asking again for a while.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, LOGGER
from ..notify.recipients import targets_for
from ..policy import ActionRequest
from ..settings import parse_time
from .baselines import AnomalyDetector, Baselines
from .habits import collect, find_habits

STORAGE_KEY = f"{DOMAIN}.learning"
KEEP_REVIEWS = 8


def action_key(domain: str, service: str, entity_ids: list[str] | tuple[str, ...]) -> str:
    return f"{domain}.{service}:{','.join(sorted(entity_ids))}"


class Learning:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.baselines = Baselines(runtime)
        self.proposals: dict[str, dict[str, Any]] = {}
        self.feedback_counts: dict[str, dict[str, int]] = {}  # action key → {"undo", "deny", "approve"}
        self.quiet_until: dict[str, str] = {}  # action key → ISO time
        self.reviews: list[dict[str, Any]] = []
        self.rejected: set[str] = set()  # habit keys people did not want
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.proposals = {p["id"]: p for p in data.get("proposals", []) if isinstance(p, dict)}
        self.feedback_counts = dict(data.get("feedback") or {})
        self.quiet_until = dict(data.get("quiet") or {})
        self.reviews = list(data.get("reviews") or [])[-KEEP_REVIEWS:]
        self.rejected = set(data.get("rejected") or [])
        self.baselines.norms = dict(data.get("norms") or {})
        hub = self.rt.module("signals")
        if hub is not None:
            hub.add_detector(AnomalyDetector(self.baselines))
        self._schedule()
        self._unsubs.append(self.rt.settings.listen("learning", lambda _k: self._schedule()))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {
            "proposals": list(self.proposals.values()),
            "feedback": self.feedback_counts,
            "quiet": self.quiet_until,
            "reviews": self.reviews[-KEEP_REVIEWS:],
            "rejected": sorted(self.rejected)[-500:],
            "norms": self.baselines.norms,
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._data, 10)
        for cb in list(self._listeners):
            cb()

    @callback
    def listen(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _schedule(self) -> None:
        for unsub in self._unsubs[1:]:
            unsub()
        del self._unsubs[1:]
        nightly = parse_time(str(self.rt.settings.get("learning.nightly_time")))
        self._unsubs.append(
            async_track_time_change(self.hass, self._nightly, hour=nightly.hour, minute=nightly.minute, second=0)
        )
        review = parse_time(str(self.rt.settings.get("learning.review_time")))
        self._unsubs.append(
            async_track_time_change(self.hass, self._maybe_review, hour=review.hour, minute=review.minute, second=0)
        )

    # ——— Nightly ———
    async def _nightly(self, _now: datetime) -> None:
        await self.nightly()

    async def nightly(self) -> None:
        if not self.rt.settings.get("learning.enabled"):
            return
        try:
            count = await self.baselines.refresh()
            LOGGER.debug("HomeAI norms for %s entities", count)
        except Exception:
            LOGGER.exception("Computing norms failed")
        if self.rt.settings.get("learning.habits"):
            try:
                await self.detect_habits()
            except Exception:
                LOGGER.exception("Finding habits failed")
        self._save()

    async def detect_habits(self, changes: dict[str, list[tuple[Any, str]]] | None = None) -> list[dict[str, Any]]:
        days = int(self.rt.settings.get("learning.habit_days"))
        if changes is None:
            changes = await collect(self.rt, days)
        found = find_habits(
            changes,
            days=days,
            min_days=int(self.rt.settings.get("learning.habit_min_days")),
            window=int(self.rt.settings.get("learning.habit_window")),
        )
        new = []
        existing = {p["key"] for p in self.proposals.values()}
        for habit in found:
            key = f"{habit['service']}:{habit['entity_id']}:{habit['kind']}"
            if key in existing or key in self.rejected:
                continue
            proposal = {
                "id": ulid_util.ulid_now().lower(),
                "key": key,
                "type": "habit",
                "created": dt_util.utcnow().isoformat(timespec="seconds"),
                "status": "pending",
                **habit,
                "title": self.rt.text(
                    "learning|habit_title",
                    what=self.rt.world.display_name(habit["entity_id"]),
                    action=habit["service"].split(".", 1)[1],
                    time=habit["time"],
                    days=self.rt.text(f"learning|{habit['kind']}"),
                ),
            }
            self.proposals[proposal["id"]] = proposal
            new.append(proposal)
        if new:
            self.rt.journal.add("decision", self.rt.text("learning|habits_found", count=len(new)))
            self._save()
        return new

    async def approve(self, proposal_id: str, user_id: str | None) -> dict[str, Any] | None:
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal["status"] != "pending":
            return None
        days = [0, 1, 2, 3, 4] if proposal["kind"] == "workday" else [5, 6]
        entry = await self.rt.module("scheduler").save(
            {
                "title": proposal["title"],
                "action": {"service": proposal["service"], "entity_ids": [proposal["entity_id"]]},
                "when": {"kind": "weekly", "time": proposal["time"], "days": days},
                "skip_when_away": True,
            },
            user_id,
        )
        proposal.update(status="approved", entry_id=entry["id"])
        memory = self.rt.module("memory")
        if memory is not None:
            memory.add(
                proposal["title"],
                scope=f"entity:{proposal['entity_id']}",
                source="learning",
                confidence=0.8,
                author=user_id,
            ).update(approved=True)
        self._save()
        return proposal

    def reject(self, proposal_id: str) -> bool:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return False
        proposal["status"] = "rejected"
        self.rejected.add(proposal["key"])
        self._save()
        return True

    # ——— Feedback ———
    def feedback(self, kind: str, record: dict[str, Any]) -> None:
        """People's reactions to HomeAI's actions: undo, deny (and approve) teach the policy."""
        request = record.get("request") or {}
        if not request.get("domain"):
            return
        key = action_key(request["domain"], request["service"], request.get("entity_ids") or [])
        counts = self.feedback_counts.setdefault(key, {})
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "deny":
            days = int(self.rt.settings.get("learning.deny_quiet_days"))
            self.quiet_until[key] = (dt_util.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
        self._save()

    def restricted(self, request: ActionRequest) -> bool:
        """An automatic action people undid too often goes back to “propose”."""
        counts = self.feedback_counts.get(action_key(request.domain, request.service, request.entity_ids), {})
        return counts.get("undo", 0) >= int(self.rt.settings.get("learning.undo_limit"))

    def quiet(self, request: ActionRequest) -> bool:
        """Recently refused: do not ask again yet."""
        until = self.quiet_until.get(action_key(request.domain, request.service, request.entity_ids))
        return bool(until and (t := dt_util.parse_datetime(until)) and t > dt_util.utcnow())

    # ——— Weekly review ———
    async def _maybe_review(self, now: datetime) -> None:
        if self.rt.settings.get("learning.enabled") and dt_util.as_local(now).weekday() == int(
            self.rt.settings.get("learning.review_weekday")
        ):
            await self.weekly_review()

    def review_facts(self) -> dict[str, Any]:
        since = dt_util.utcnow() - timedelta(days=7)
        engine = self.rt.module("situations")
        resolved = [s for s in engine.resolved if s.resolved_at and s.resolved_at >= since] if engine else []
        kinds: dict[str, int] = {}
        for s in resolved:
            kinds[s.kind] = kinds.get(s.kind, 0) + 1
        repair = self.rt.module("repair")
        executor = self.rt.module("executor")
        actions = (
            [r for r in executor.recent if (dt_util.parse_datetime(r["ts"]) or since) >= since] if executor else []
        )
        approvals = self.rt.module("approvals")
        decided = [a for a in (approvals.items.values() if approvals else []) if a["created"] >= since.isoformat()]
        ai = self.rt.module("ai")
        suggestions = [
            key
            for key, c in self.feedback_counts.items()
            if c.get("approve", 0) >= int(self.rt.settings.get("learning.raise_after"))
            and not c.get("deny")
            and not c.get("undo")
        ]
        return {
            "situations_resolved": len(resolved),
            "top_kinds": sorted(kinds.items(), key=lambda kv: -kv[1])[:5],
            "open": len(engine.open()) if engine else 0,
            "repairs": repair.stats if repair else {},
            "actions": {
                "done": sum(1 for a in actions if a["result"]["status"] in ("done", "unverified")),
                "undone": sum(1 for a in actions if a.get("undone")),
                "observed": sum(1 for a in actions if a["result"]["status"] == "observed"),
            },
            "approvals": {
                s: sum(1 for a in decided if a["status"] == s) for s in ("approved", "denied", "expired", "pending")
            },
            "ai_cost_week": round(
                sum(
                    float(d.get("cost", 0))
                    for day, d in ai.ledger.days.items()
                    if day >= (dt_util.now() - timedelta(days=7)).date().isoformat()
                ),
                4,
            )
            if ai
            else 0,
            "proposals_pending": sum(1 for p in self.proposals.values() if p["status"] == "pending"),
            "raise_autonomy": suggestions[:5],
        }

    def review_text(self, facts: dict[str, Any]) -> str:
        t = self.rt.text
        lines = [t("learning|review_situations", count=facts["situations_resolved"], open=facts["open"])]
        if facts["top_kinds"]:
            lines.append(t("learning|review_top", kinds=[f"{k} ({n})" for k, n in facts["top_kinds"]]))
        a = facts["actions"]
        lines.append(t("learning|review_actions", done=a["done"], undone=a["undone"], observed=a["observed"]))
        ap = facts["approvals"]
        lines.append(
            t("learning|review_approvals", approved=ap["approved"], denied=ap["denied"], expired=ap["expired"])
        )
        if facts["ai_cost_week"]:
            lines.append(t("learning|review_cost", cost=f"{facts['ai_cost_week']:.2f}"))
        if facts["proposals_pending"]:
            lines.append(t("learning|review_proposals", count=facts["proposals_pending"]))
        if facts["raise_autonomy"]:
            lines.append(t("learning|review_raise", actions=facts["raise_autonomy"]))
        return "\n".join(lines)

    async def weekly_review(self) -> dict[str, Any]:
        facts = self.review_facts()
        text = self.review_text(facts)
        ai = self.rt.module("ai")
        if ai is not None and self.rt.settings.get("learning.review_ai"):
            try:
                better = await ai.narrate_digest(text)
                if better:
                    text = better
            except Exception:
                LOGGER.debug("AI review failed")
        review = {"ts": dt_util.utcnow().isoformat(timespec="seconds"), "facts": facts, "text": text}
        self.reviews.append(review)
        del self.reviews[:-KEEP_REVIEWS]
        title = self.rt.text("learning|review_title")
        persistent_notification.async_create(self.hass, text, title=title, notification_id="homeai_weekly_review")
        router = self.rt.module("notify")
        if router is not None and self.rt.settings.get("learning.review_push"):
            for person in self.rt.presence.residents():
                if person.role != "admin":
                    continue
                for target in targets_for(self.hass, self.rt.settings, person.entity_id):
                    try:
                        await router._send(target, title, text, {"tag": "homeai_review", "group": "homeai"})
                    except Exception:
                        LOGGER.debug("Review to %s failed", target)
        self.rt.journal.add("decision", self.rt.text("learning|review_sent"))
        self._save()
        return review

    def diagnostics(self) -> dict[str, Any]:
        return {
            "norms": len(self.baselines.norms),
            "refreshed": self.baselines.refreshed,
            "proposals": list(self.proposals.values())[-20:],
            "feedback": self.feedback_counts,
        }
