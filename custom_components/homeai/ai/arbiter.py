"""The arbiter (P3): decisions on hard cases from a dossier, without tools.

Cases: P1 and P2 disagree; an action waits for approval while it is risky or nobody is home; repairs failed on a
serious matter; an explicit request. The arbiter's decision is recorded with its dossier. It may approve waiting
actions only up to R3 and only when the administrator allows it (`ai.arbiter_can_approve`); for higher classes it
adds a recommendation to the request for the administrator. It never approves R5 or R6.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, LOGGER
from ..situations.model import Phase, Situation
from .context import entity_lines, home_card, moment_card
from .missions.triage import situation_text, validate
from .privacy import Privacy, clean
from .prompts import ARBITER, ARBITER_SCHEMA
from .providers.base import AIRequest

STORAGE_KEY = f"{DOMAIN}.dossiers"
KEEP = 50
MAX_ARBITER_APPROVAL = 3


class Arbiter:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.dossiers: list[dict[str, Any]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._tasks: set[asyncio.Task] = set()
        self._busy: set[str] = set()
        self._today: tuple[str, int] = ("", 0)

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.dossiers = list(data.get("dossiers") or [])[-KEEP:]
        approvals = self.rt.module("approvals")
        if approvals is not None:
            self._unsubs.append(approvals.listen(self._on_approval))
        engine = self.rt.module("situations")
        if engine is not None:
            self._unsubs.append(engine.listen(self._on_situation))

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        for task in list(self._tasks):
            task.cancel()
        await self._store.async_save({"dossiers": self.dossiers[-KEEP:]})

    # ——— When ———
    def enabled(self, case: str | None = None) -> bool:
        ai = self.rt.module("ai")
        settings = self.rt.settings
        if ai is None or not ai.available("p3") or not settings.get("ai.arbiter_enabled"):
            return False
        return case is None or bool(settings.get(f"ai.arbiter_{case}"))

    def _budget(self) -> bool:
        today = dt_util.now().date().isoformat()
        day, count = self._today
        if day != today:
            count = 0
        if count >= int(self.rt.settings.get("ai.arbiter_per_day")):
            return False
        self._today = (today, count + 1)
        return True

    def _spawn(self, key: str, coro: Any) -> None:
        if key in self._busy:
            coro.close()
            return
        self._busy.add(key)

        async def run() -> None:
            try:
                await coro
            except Exception:
                LOGGER.exception("Arbiter failed on %s", key)
            finally:
                self._busy.discard(key)

        task = self.hass.async_create_background_task(run(), f"homeai arbiter {key}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def queue_dispute(self, s: Situation) -> None:
        if self.enabled("disputes"):
            self._spawn(f"s:{s.id}", self.decide_situation(s, "dispute"))

    def _on_situation(self, event: str, s: Situation) -> None:
        if (
            event == "escalated"
            and s.repair.get("status") == "failed"
            and s.severity >= 3
            and self.enabled("failed_repairs")
            and not s.assessment.get("arbiter")
        ):
            self._spawn(f"s:{s.id}", self.decide_situation(s, "failed_repair"))

    def _on_approval(self, item: dict[str, Any]) -> None:
        if item.get("status") != "pending" or item.get("arbiter") or not self.enabled("approvals"):
            return
        risk = int(item.get("risk", 0))
        nobody_home = not self.rt.presence.someone_home()
        if risk >= 4 or (risk >= 2 and nobody_home):
            self._spawn(f"a:{item['id']}", self.decide_approval(item))

    # ——— Dossiers ———
    def _privacy(self) -> Privacy:
        ai = self.rt.module("ai")
        return Privacy(self.rt, ai.privacy_level(ai.first("p3")))

    async def _ask(self, case: str, subject: str, dossier: str, effort: str) -> dict[str, Any] | None:
        if not self._budget():
            LOGGER.debug("Arbiter daily limit reached")
            return None
        request = AIRequest(
            system=ARBITER,
            messages=[{"role": "user", "content": dossier}],
            schema=ARBITER_SCHEMA,
            max_tokens=32000,
            effort=effort,
            purpose=f"arbiter_{case}",
        )
        response = await self.rt.module("ai").ask("p3", request)
        if response is None or not isinstance(response.data, dict):
            return None
        record = {
            "id": ulid_util.ulid_now().lower(),
            "ts": dt_util.utcnow().isoformat(timespec="seconds"),
            "case": case,
            "subject": subject,
            "dossier": dossier[:20000],
            "decision": response.data,
            "model": response.model,
            "cost": round(response.cost, 4),
        }
        self.dossiers.append(record)
        del self.dossiers[:-KEEP]
        self._store.async_delay_save(lambda: {"dossiers": self.dossiers[-KEEP:]}, 5)
        return record

    def _decision(self, raw: dict[str, Any], privacy: Privacy) -> dict[str, Any] | None:
        if raw.get("decision") not in ("approve", "reject", "escalate_human"):
            return None
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
        except TypeError, ValueError:
            return None
        return {
            "decision": raw["decision"],
            "confidence": confidence,
            "reason": privacy.restore(clean(raw.get("reason", ""), 800)),
            "conditions": [privacy.restore(clean(c, 200)) for c in raw.get("conditions") or [] if isinstance(c, str)][
                :5
            ],
        }

    async def decide_situation(self, s: Situation, case: str = "request") -> dict[str, Any] | None:
        """Settle a situation: disagreement between tiers, failed repairs, or a person's request."""
        if not self.enabled():
            return None
        privacy = self._privacy()
        parts = [home_card(self.rt, privacy), moment_card(self.rt, privacy), situation_text(self.rt, s, privacy)]
        if dispute := s.assessment.get("dispute"):
            parts.append(
                "<assessments>\n"
                + "\n".join(
                    f"{tier.upper()}: severity {a['severity']}, who {a['who']}, "
                    f"confidence {a['confidence']:.2f}: {clean(a['reason'], 300)}"
                    for tier, a in dispute.items()
                )
                + "\n</assessments>"
            )
        if s.repair:
            parts.append(f"<repair>{clean(s.repair, 600)}</repair>")
        parts.append(
            f"Case: {case}. Decide whether the current assessment stands (approve) or not (reject), or "
            "whether a person must decide; give your own severity and who."
        )
        record = await self._ask(
            case, f"situation:{s.id}", "\n\n".join(parts), str(self.rt.settings.get("ai.arbiter_effort"))
        )
        if record is None or s.phase is not Phase.OPEN:
            return None
        decision = self._decision(record["decision"], privacy)
        assessment = validate(record["decision"], s, dict(s.assessment), privacy)
        if decision is None or assessment is None:
            return None
        self.rt.module("triage").apply_ai(s, {**assessment, "reason": decision["reason"]}, "p3")
        s.assessment["arbiter"] = {**decision, "dossier_id": record["id"]}
        s.log("arbiter", decision=decision["decision"], dossier=record["id"])
        self.rt.journal.add(
            "decision",
            self.rt.text(
                "journal|arbiter_decided",
                title=s.title(self.rt.language),
                decision=self.rt.text(f"ai|decision_{decision['decision']}"),
                reason=decision["reason"],
            ),
            situation_id=s.id,
        )
        await self.rt.module("situations").reassessed(s)
        return decision

    async def decide_approval(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Review an action waiting for approval; approve it only within the arbiter's limits."""
        if not self.enabled():
            return None
        privacy = self._privacy()
        request = item["request"]
        risk = int(item["risk"])
        parts = [home_card(self.rt, privacy), moment_card(self.rt, privacy)]
        what = clean(item["what"], 200) if privacy.level != "minimal" else f"{request['domain']}.{request['service']}"
        parts.append(
            "<proposed_action>\n"
            f"What: {what}\n"
            f"Risk class: R{risk}\nRequested by: {request.get('actor')}\nWhy: {clean(item.get('reason') or '', 300)}\n"
            "</proposed_action>"
        )
        lines = entity_lines(self.rt, privacy, request.get("entity_ids") or [])
        if lines:
            parts.append("<entities>\n" + "\n".join(lines) + "\n</entities>")
        if (sid := request.get("situation_id")) and (s := self.rt.module("situations").get(sid)):
            parts.append(situation_text(self.rt, s, privacy))
        parts.append("Decide whether this action should run now.")
        effort = "max" if risk >= 5 else str(self.rt.settings.get("ai.arbiter_effort"))
        record = await self._ask("approval", f"approval:{item['id']}", "\n\n".join(parts), effort)
        if record is None:
            return None
        decision = self._decision(record["decision"], privacy)
        if decision is None:
            return None
        approvals = self.rt.module("approvals")
        item["arbiter"] = {**decision, "dossier_id": record["id"]}
        may_approve = (
            decision["decision"] == "approve"
            and risk <= MAX_ARBITER_APPROVAL
            and self.rt.settings.get("ai.arbiter_can_approve")
            and decision["confidence"] >= float(self.rt.settings.get("ai.arbiter_min_confidence"))
        )
        if may_approve and item["status"] == "pending":
            await approvals.approve_as_arbiter(item["id"], decision)
        elif (
            decision["decision"] == "reject"
            and risk <= MAX_ARBITER_APPROVAL
            and self.rt.settings.get("ai.arbiter_can_approve")
        ):
            await approvals.deny_as_arbiter(item["id"], decision)
        else:
            approvals.note(item)
        self.rt.journal.add(
            "decision",
            self.rt.text(
                "journal|arbiter_reviewed",
                what=item["what"],
                decision=self.rt.text(f"ai|decision_{decision['decision']}"),
                reason=decision["reason"],
            ),
        )
        return decision

    def diagnostics(self) -> dict[str, Any]:
        return {
            "dossiers": [
                {k: d[k] for k in ("id", "ts", "case", "subject", "decision", "cost")} for d in self.dossiers[-10:]
            ]
        }
