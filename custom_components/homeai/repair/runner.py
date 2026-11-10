"""Repair runner: a situation processor that tries playbooks before people are told.

States in `situation.repair`: waiting → trying → verifying → succeeded, or → waiting again (backoff) until
`repair.max_attempts`, then failed. Refused by policy: blocked. Waiting for someone's yes: awaiting_approval.
While waiting, trying or verifying, triage says nobody is needed (except critical severity). A failed or
blocked repair escalates the situation so people are told, with the note that HomeAI tried.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..situations.model import Phase, Situation
from .playbooks import PLAYBOOKS, protective_requests

ACTIVE = ("waiting", "trying", "verifying")


class RepairRunner:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self._unsubs: list[Callable[[], None]] = []
        self.stats: dict[str, dict[str, int]] = {}

    async def async_setup(self) -> None:
        self.rt.module("situations").add_processor("repair", self.process)
        self._unsubs.append(self.rt.on_tick(self.tick))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ——— Situation events ———
    async def process(self, event: str, s: Situation) -> None:
        if event == "opened":
            await self._protect(s)
            self.start(s)
        elif event == "updated" and not s.repair:
            self.start(s)
        elif event == "handled" and s.repair.get("status") in ACTIVE:
            self._set(s, "cancelled")
        elif event in ("resolved", "dismissed") and s.repair.get("status") in (*ACTIVE, "awaiting_approval"):
            tried = s.repair.get("attempts", 0) > 0
            self._set(s, "succeeded" if event == "resolved" and tried else "cancelled")
            if event == "resolved" and tried:
                self._count(s.repair["playbook"], "succeeded")
                self.rt.journal.add(
                    "repair",
                    self.rt.text("journal|repair_succeeded", title=s.title(self.rt.language)),
                    situation_id=s.id,
                    result="succeeded",
                )

    def plan(self, s: Situation) -> tuple[str, dict[str, Any]] | None:
        p = s.primary
        if p is None:
            return None
        enabled = set(self.rt.settings.get("repair.playbooks"))
        if p.repair and p.repair.get("playbook") in PLAYBOOKS and p.repair["playbook"] in enabled:
            params = {k: v for k, v in p.repair.items() if k != "playbook"}
            if self._never_reload(params.get("entry_id")):
                return None
            return p.repair["playbook"], params
        if p.action and self.rt.settings.get("repair.quick_actions") and "action" in enabled:
            return "action", dict(p.action)
        return None

    def _never_reload(self, entry_id: str | None) -> bool:
        """The administrator listed this integration (domain or entry id) as one HomeAI never reloads."""
        if not entry_id:
            return False
        never = set(self.rt.settings.get("repair.never_reload"))
        entry = self.rt.hass.config_entries.async_get_entry(entry_id)
        return entry_id in never or (entry is not None and entry.domain in never)

    def start(self, s: Situation, now: datetime | None = None) -> None:
        if not self.rt.settings.get("repair.enabled") or s.phase is not Phase.OPEN:
            return
        planned = self.plan(s)
        if planned is None:
            return
        key, params = planned
        playbook = PLAYBOOKS[key]
        now = now or dt_util.utcnow()
        wait = int(self.rt.settings.get(playbook.wait_setting))
        s.repair = {
            "playbook": key,
            "params": params,
            "status": "waiting",
            "due": (now + timedelta(minutes=wait)).isoformat(timespec="seconds"),
            "attempts": 0,
            "results": [],
        }
        s.log("repair_planned", playbook=key)
        self._reassess(s)

    async def _protect(self, s: Situation) -> None:
        if not self.rt.settings.get("repair.protective_enabled"):
            return
        executor = self.rt.module("executor")
        for request in protective_requests(self.rt, s):
            result = await executor.execute(request)
            s.log("protective_action", status=result.status, what=executor.describe(request))

    # ——— Time ———
    async def tick(self, now: datetime) -> None:
        engine = self.rt.module("situations")
        changed = False
        for s in list(engine.situations.values()):
            status = s.repair.get("status")
            if s.phase is not Phase.OPEN or status not in ("waiting", "verifying"):
                continue
            if status == "waiting":
                due = dt_util.parse_datetime(s.repair.get("due") or "")
                if due is not None and due <= now:
                    await self.attempt(s, now)
                    changed = True
            elif status == "verifying":
                until = dt_util.parse_datetime(s.repair.get("verify_until") or "")
                if until is not None and until <= now:
                    await self._retry_or_fail(s, now, "still_open")
                    changed = True
        if changed:
            engine.save()

    async def attempt(self, s: Situation, now: datetime | None = None) -> None:
        now = now or dt_util.utcnow()
        key = s.repair["playbook"]
        playbook = PLAYBOOKS[key]
        requests = playbook.build(self.rt, s, s.repair.get("params") or {})
        if not requests:
            if (s.repair.get("params") or {}).get("paused"):
                s.repair["due"] = (now + timedelta(minutes=int(self.rt.settings.get(playbook.wait_setting)))).isoformat(
                    timespec="seconds"
                )
                return
            await self._finish_failed(s, "blocked", "nothing_to_do")
            return
        self._set(s, "trying")
        s.repair["attempts"] = s.repair.get("attempts", 0) + 1
        self._count(key, "attempts")
        self.rt.journal.add(
            "repair",
            self.rt.text("journal|repair_started", title=s.title(self.rt.language), playbook=key),
            situation_id=s.id,
        )
        executor = self.rt.module("executor")
        outcome = "ok"
        for request in requests:
            request.playbook = key
            request.actor = playbook.actor
            result = await executor.execute(request)
            s.repair["results"] = [*s.repair.get("results", [])[-9:], {"status": result.status, "risk": result.risk}]
            if result.status == "pending_approval":
                outcome = "approval"
                s.repair["approval_id"] = result.approval_id
                break
            if result.status in ("denied", "observed", "blocked", "invalid"):
                outcome = result.status
                break
            if result.status == "failed":
                outcome = "failed"
        if outcome == "ok":
            self._set(s, "verifying")
            s.repair["verify_until"] = (
                now + timedelta(minutes=int(self.rt.settings.get("repair.verify_minutes")))
            ).isoformat(timespec="seconds")
            self._reassess(s)
        elif outcome == "approval":
            self._set(s, "awaiting_approval")
            await self._escalate(s, "awaiting_approval")
        elif outcome == "failed":
            await self._retry_or_fail(s, now, "action_failed")
        else:
            await self._finish_failed(s, "blocked", outcome)

    async def _retry_or_fail(self, s: Situation, now: datetime, reason: str) -> None:
        if s.repair.get("attempts", 0) < int(self.rt.settings.get("repair.max_attempts")):
            backoff = int(self.rt.settings.get("repair.backoff_minutes")) * s.repair.get("attempts", 1)
            self._set(s, "waiting")
            s.repair["due"] = (now + timedelta(minutes=backoff)).isoformat(timespec="seconds")
            self._reassess(s)
            return
        await self._finish_failed(s, "failed", reason)

    async def _finish_failed(self, s: Situation, status: str, reason: str) -> None:
        self._set(s, status)
        s.repair["reason"] = reason
        self._count(s.repair["playbook"], status)
        self.rt.journal.add(
            "repair",
            self.rt.text(f"journal|repair_{status}", title=s.title(self.rt.language), reason=reason),
            situation_id=s.id,
            result=status,
        )
        await self._escalate(s, reason)

    async def _escalate(self, s: Situation, reason: str) -> None:
        await self.rt.module("situations").escalate(s, reason)

    def _set(self, s: Situation, status: str) -> None:
        s.repair["status"] = status
        s.log("repair", status=status)

    def _reassess(self, s: Situation) -> None:
        triage = self.rt.module("triage")
        if triage is not None and s.signals:
            s.assessment = triage.assess(s)

    def _count(self, key: str, what: str) -> None:
        counters = self.stats.setdefault(key, {})
        counters[what] = counters.get(what, 0) + 1

    def diagnostics(self) -> dict[str, Any]:
        return {"stats": self.stats}
