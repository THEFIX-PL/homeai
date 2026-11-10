"""Approvals: actions waiting for a person's yes.

Residents may approve R1–R2, administrators approve R3 and above (R6 is never run on approval: an
administrator does it themselves with confirmation). Requests go to the panel, a persistent notification and
phones with Approve / Deny buttons, and expire after `policy.approval_minutes`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import Event, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, LOGGER
from ..notify.recipients import targets_for
from ..policy import ActionRequest, Decision

STORAGE_KEY = f"{DOMAIN}.approvals"
EVENT_APPROVAL = "homeai_approval"
PREFIX = "HOMEAI_APPROVAL_"
HISTORY = 50


class Approvals:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self._store: Store[dict[str, Any]] = Store(self.hass, 1, STORAGE_KEY)
        self.items: dict[str, dict[str, Any]] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    async def async_setup(self) -> None:
        data = await self._store.async_load() or {}
        self.items = {a["id"]: a for a in data.get("items", []) if isinstance(a, dict) and "id" in a}
        self._unsubs += [
            self.rt.on_tick(self.tick),
            self.hass.bus.async_listen("mobile_app_notification_action", self._on_action),
        ]

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        pending = [a for a in self.items.values() if a["status"] == "pending"]
        done = sorted((a for a in self.items.values() if a["status"] != "pending"), key=lambda a: a["created"])
        return {"items": pending + done[-HISTORY:]}

    def _save(self) -> None:
        self._store.async_delay_save(self._data, 2)

    @callback
    def listen(self, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _changed(self, item: dict[str, Any]) -> None:
        self._save()
        self.hass.bus.async_fire(EVENT_APPROVAL, {k: item[k] for k in ("id", "status", "what", "risk")})
        for cb in list(self._listeners):
            try:
                cb(item)
            except Exception:
                LOGGER.exception("Approval listener failed")

    def pending(self) -> list[dict[str, Any]]:
        return sorted((a for a in self.items.values() if a["status"] == "pending"), key=lambda a: a["created"])

    # ——— Requests ———
    async def create(self, request: ActionRequest, decision: Decision, what: str) -> dict[str, Any]:
        # the same request already waiting: do not ask twice
        for item in self.pending():
            if item["request"] == request.as_dict():
                return item
        now = dt_util.utcnow()
        item = {
            "id": ulid_util.ulid_now().lower(),
            "request": request.as_dict(),
            "what": what,
            "risk": int(decision.risk),
            "reason": request.reason or decision.reason,
            "approver": decision.approver or "admins",
            "created": now.isoformat(timespec="seconds"),
            "expires": (now + timedelta(minutes=int(self.rt.settings.get("policy.approval_minutes")))).isoformat(
                timespec="seconds"
            ),
            "status": "pending",
            "decided_by": None,
            "result": None,
        }
        self.items[item["id"]] = item
        self.rt.journal.add(
            "approval", self.rt.text("journal|approval_requested", what=what), situation_id=request.situation_id
        )
        await self._notify(item)
        self._changed(item)
        return item

    async def _notify(self, item: dict[str, Any]) -> None:
        title = self.rt.text("notify|approval_title")
        message = self.rt.text("notify|approval_message", what=item["what"], reason=item["reason"] or "—")
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=f"homeai_approval_{item['id']}"
        )
        people = [p for p in self.rt.presence.residents() if item["approver"] == "residents" or p.role == "admin"]
        data = {
            "tag": f"homeai_approval_{item['id']}",
            "group": "homeai",
            "actions": [
                {"action": f"{PREFIX}APPROVE_{item['id']}", "title": self.rt.text("notify|action_approve")},
                {"action": f"{PREFIX}DENY_{item['id']}", "title": self.rt.text("notify|action_deny")},
            ],
            "push": {"interruption-level": "time-sensitive" if item["risk"] >= 3 else "active"},
        }
        router = self.rt.module("notify")
        for person in people:
            if person.sleep.asleep:
                continue
            for target in targets_for(self.hass, self.rt.settings, person.entity_id):
                try:
                    if router is not None:
                        await router._send(target, title, message, data)
                except Exception as err:
                    LOGGER.debug("Approval request to %s failed: %s", target, err)

    async def _clear(self, item: dict[str, Any]) -> None:
        persistent_notification.async_dismiss(self.hass, f"homeai_approval_{item['id']}")
        router = self.rt.module("notify")
        if router is None:
            return
        for person in self.rt.presence.residents():
            for target in targets_for(self.hass, self.rt.settings, person.entity_id):
                if self.hass.states.get(target) is not None:
                    continue
                try:
                    await router._send(target, "", "clear_notification", {"tag": f"homeai_approval_{item['id']}"})
                except Exception:
                    LOGGER.debug("Clearing approval on %s failed", target)

    # ——— Decisions ———
    async def can_decide(self, item: dict[str, Any], user_id: str | None) -> bool:
        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        if user is None or not user.is_active:
            return False
        if user.is_admin:
            return True
        if item["approver"] != "residents":
            return False
        person = next((p for p in self.rt.presence.residents() if p.user_id == user_id), None)
        return person is not None

    async def approve(self, approval_id: str, user_id: str | None) -> dict[str, Any] | None:
        item = self.items.get(approval_id)
        if item is None or item["status"] != "pending" or not await self.can_decide(item, user_id):
            return None
        who = await self._name(user_id)
        item.update(status="approved", decided_by=who, decided_at=dt_util.utcnow().isoformat(timespec="seconds"))
        request = ActionRequest.from_dict(item["request"])
        request.approved_by = who
        result = await self.rt.module("executor").execute(request)
        item["result"] = result.as_dict()
        self.rt.journal.add("approval", self.rt.text("journal|approval_granted", what=item["what"], who=who))
        await self._clear(item)
        self._changed(item)
        return item

    async def deny(self, approval_id: str, user_id: str | None) -> dict[str, Any] | None:
        item = self.items.get(approval_id)
        if item is None or item["status"] != "pending" or not await self.can_decide(item, user_id):
            return None
        who = await self._name(user_id)
        item.update(status="denied", decided_by=who, decided_at=dt_util.utcnow().isoformat(timespec="seconds"))
        self.rt.journal.add("approval", self.rt.text("journal|approval_denied", what=item["what"], who=who))
        learning = self.rt.module("learning")
        if learning is not None:
            learning.feedback("deny", item)
        await self._clear(item)
        self._changed(item)
        return item

    def note(self, item: dict[str, Any]) -> None:
        """Something was added to a request (e.g. the arbiter's recommendation)."""
        self._changed(item)

    async def approve_as_arbiter(self, approval_id: str, decision: dict[str, Any]) -> dict[str, Any] | None:
        """The arbiter approves within its limits (checked by the arbiter; never above R3, never R6)."""
        item = self.items.get(approval_id)
        if item is None or item["status"] != "pending" or int(item["risk"]) > 3:
            return None
        who = self.rt.text("ai|arbiter_name")
        item.update(status="approved", decided_by=who, decided_at=dt_util.utcnow().isoformat(timespec="seconds"))
        request = ActionRequest.from_dict(item["request"])
        request.approved_by = who
        result = await self.rt.module("executor").execute(request)
        item["result"] = result.as_dict()
        self.rt.journal.add("approval", self.rt.text("journal|approval_granted", what=item["what"], who=who))
        await self._clear(item)
        self._changed(item)
        return item

    async def deny_as_arbiter(self, approval_id: str, decision: dict[str, Any]) -> dict[str, Any] | None:
        item = self.items.get(approval_id)
        if item is None or item["status"] != "pending":
            return None
        who = self.rt.text("ai|arbiter_name")
        item.update(status="denied", decided_by=who, decided_at=dt_util.utcnow().isoformat(timespec="seconds"))
        self.rt.journal.add("approval", self.rt.text("journal|approval_denied", what=item["what"], who=who))
        await self._clear(item)
        self._changed(item)
        return item

    async def tick(self, now: datetime) -> None:
        for item in self.pending():
            expires = dt_util.parse_datetime(item["expires"])
            if expires is not None and expires <= now:
                item["status"] = "expired"
                self.rt.journal.add("approval", self.rt.text("journal|approval_expired", what=item["what"]))
                await self._clear(item)
                self._changed(item)

    async def _name(self, user_id: str | None) -> str:
        for p in self.rt.world.persons.values():
            if p.user_id and p.user_id == user_id:
                return p.name
        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        return (user.name if user else None) or "?"

    @callback
    def _on_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        if not action.startswith(PREFIX):
            return
        verb, _, approval_id = action[len(PREFIX) :].partition("_")
        if verb == "APPROVE":
            self.hass.async_create_task(self.approve(approval_id, event.context.user_id))
        elif verb == "DENY":
            self.hass.async_create_task(self.deny(approval_id, event.context.user_id))

    def diagnostics(self) -> dict[str, Any]:
        return {"pending": self.pending()}
