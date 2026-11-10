"""Notification router: who hears about a situation, through which channel, and when it escalates.

Each severity has a ladder of steps (`notify.ladder_<severity>`): after N minutes, to whom (everyone, people at
home, administrators, people awake at home), through which channels (push, persistent notification, speech,
event for custom displays), whether to repeat and whether it may break quiet hours. People asleep are skipped
until they wake unless the step is critical. Acknowledging (“Got it”), taking a situation (“I'll handle it”),
snoozing, dismissing or resolving stops escalation and clears what was sent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from ..const import EVENT_NOTIFICATION, LOGGER
from ..settings import parse_time
from ..situations.model import Phase, Situation
from ..world.presence import PersonState
from .recipients import targets_for

ACTION_PREFIX = "HOMEAI_"
ACTIONS = ("ACK", "HANDLE", "SNOOZE")
PERSISTENT_PREFIX = "homeai_"


class NotificationRouter:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self._unsubs: list[Callable[[], None]] = []
        self._digest_unsubs: list[Callable[[], None]] = []
        self._daily: dict[str, tuple[date, int]] = {}

    async def async_setup(self) -> None:
        engine = self.rt.module("situations")
        engine.add_processor("notify", self.process)
        self._unsubs += [
            self.rt.on_tick(self.tick),
            self.hass.bus.async_listen("mobile_app_notification_action", self._on_action),
            self.rt.settings.listen("notify.digest", lambda _k: self._setup_digest()),
        ]
        self._setup_digest()

    async def async_unload(self) -> None:
        for unsub in self._unsubs + self._digest_unsubs:
            unsub()
        self._unsubs.clear()
        self._digest_unsubs.clear()

    # ——— Lifecycle events ———
    async def process(self, event: str, s: Situation) -> None:
        if event in ("opened", "updated", "escalated"):
            await self.deliver(s)
        elif event in ("acknowledged", "handled", "dismissed", "snoozed", "resolved"):
            await self.clear(s, event)

    async def tick(self, now: datetime) -> None:
        engine = self.rt.module("situations")
        changed = False
        for s in engine.open():
            changed |= await self.deliver(s, now)
        if changed:
            engine.save()

    # ——— Delivery ———
    def ladder(self, severity: int) -> list[dict[str, Any]]:
        return list(self.rt.settings.get(f"notify.ladder_{max(0, min(4, severity))}"))

    def recipients(self, to: str, now: datetime) -> list[PersonState]:
        residents = self.rt.presence.residents(now)
        if to == "all":
            return residents
        if to == "home":
            return [p for p in residents if p.home]
        if to == "home_or_all":
            home = [p for p in residents if p.home]
            return home or residents
        if to == "admins":
            return [p for p in residents if p.role == "admin"]
        if to == "awake_home":
            return [p for p in residents if p.home and not p.sleep.asleep]
        return []

    async def deliver(self, s: Situation, now: datetime | None = None) -> bool:
        """Send every step that is due and not sent yet. Returns whether anything was sent."""
        now = now or dt_util.utcnow()
        settings = self.rt.settings
        severity = s.severity
        if s.phase is not Phase.OPEN or s.muted(now):
            return False
        if settings.get("notify.paused") and not (severity >= 4 and settings.get("notify.paused_allows_critical")):
            return False
        if s.assessment.get("who") == "nobody" and severity < 4:
            return False  # the home is handling it (repair) or nobody is needed
        opened = s.opened_at or now
        sent: dict[str, dict[str, str]] = s.notify.setdefault("sent", {})
        anything = False
        for index, step in enumerate(self.ladder(severity)):
            if now < opened + timedelta(minutes=step.get("after", 0)):
                continue
            done = sent.setdefault(f"{severity}:{index}", {})
            critical = bool(step.get("critical"))
            channels = step.get("channels") or []
            people = self.recipients(step.get("to", "none"), now)
            if "persistent" in channels and "_persistent" not in done:
                self._persistent(s)
                done["_persistent"] = now.isoformat(timespec="seconds")
                anything = True
            if "event" in channels and "_event" not in done:
                self._event(s, step)
                done["_event"] = now.isoformat(timespec="seconds")
                anything = True
            awake = critical or any(not p.sleep.asleep for p in people)
            if "tts" in channels and "_tts" not in done and awake and await self._speak(s):
                done["_tts"] = now.isoformat(timespec="seconds")
                anything = True
            if "push" not in channels:
                continue
            repeat = timedelta(minutes=step.get("repeat", 0))
            for person in people:
                last = dt_util.parse_datetime(done[person.entity_id]) if person.entity_id in done else None
                if last is not None and (not repeat or now - last < repeat):
                    continue
                if person.sleep.asleep and not critical:
                    continue
                if not critical and not self._within_daily_limit(person.entity_id):
                    continue
                if await self._push(s, person, critical=critical, severity=severity):
                    done[person.entity_id] = now.isoformat(timespec="seconds")
                    anything = True
                    if not critical:
                        self._count_daily(person.entity_id)
        if anything:
            s.log("notified", severity=severity)
        return anything

    def _within_daily_limit(self, person_id: str) -> bool:
        today = dt_util.now().date()
        day, count = self._daily.get(person_id, (today, 0))
        if day != today:
            count = 0
        return count < int(self.rt.settings.get("notify.max_per_day"))

    def _count_daily(self, person_id: str) -> None:
        today = dt_util.now().date()
        day, count = self._daily.get(person_id, (today, 0))
        self._daily[person_id] = (today, (count if day == today else 0) + 1)

    def message(self, s: Situation) -> tuple[str, str]:
        lang = self.rt.language
        title = s.title(lang)
        parts = [s.description(lang)]
        who = s.assessment.get("who") or "member"
        parts.append(self.rt.text(f"notify|who_{who}"))
        if s.repair.get("attempts"):
            parts.append(self.rt.text("notify|repair_failed"))
        message = " ".join(p for p in parts if p)
        variables = {
            "title": title,
            "message": message,
            "description": s.description(lang),
            "severity": s.severity,
            "category": str(s.category),
            "kind": s.kind,
            "who": who,
            "who_text": self.rt.text(f"notify|who_{who}"),
            "repair_failed": bool(s.repair.get("attempts")),
            "situation_id": s.id,
            "entities": list(s.entities),
        }
        return self._render("notify.template_title", variables, title), self._render(
            "notify.template_message", variables, message
        )

    def _render(self, key: str, variables: dict[str, Any], fallback: str) -> str:
        """The administrator's template (Home Assistant template syntax), or the built-in text when it is empty,
        fails or renders nothing."""
        source = str(self.rt.settings.get(key) or "").strip()
        if not source:
            return fallback
        from homeassistant.helpers.template import Template

        try:
            text = str(Template(source, self.hass).async_render(variables, parse_result=False)).strip()
        except Exception as err:  # a broken template must never stop a notification
            LOGGER.warning("Notification template %s failed: %s", key, err)
            return fallback
        return text[:4000] or fallback

    async def _push(self, s: Situation, person: PersonState, *, critical: bool, severity: int) -> bool:
        targets = targets_for(self.hass, self.rt.settings, person.entity_id)
        if not targets:
            return False
        title, message = self.message(s)
        level = (
            "critical"
            if critical and self.rt.settings.get("notify.critical_sound")
            else ("time-sensitive" if severity >= 3 else "active")
        )
        data = {
            "tag": f"homeai_{s.id}",
            "group": "homeai",
            "url": f"/{self.rt.settings.get('notify.open_path')}?situation={s.id}",
            "clickAction": f"/{self.rt.settings.get('notify.open_path')}?situation={s.id}",
            "actions": [
                {"action": f"{ACTION_PREFIX}ACK_{s.id}", "title": self.rt.text("notify|action_ack")},
                {"action": f"{ACTION_PREFIX}HANDLE_{s.id}", "title": self.rt.text("notify|action_handle")},
                {"action": f"{ACTION_PREFIX}SNOOZE_{s.id}", "title": self.rt.text("notify|action_snooze")},
            ],
            "push": {"interruption-level": level},
            "priority": "high" if severity >= 3 else "normal",
            "ttl": 0 if severity >= 3 else 3600,
        }
        sent_any = False
        for target in targets:
            try:
                await self._send(target, title, message, data)
                sent_any = True
            except Exception as err:
                LOGGER.warning("Notification to %s failed: %s", target, err)
        if sent_any:
            used = s.notify.setdefault("targets", [])
            for t in targets:
                if t not in used:
                    used.append(t)
            self.rt.journal.add(
                "notification",
                self.rt.text("journal|notified", title=title, who=person.name),
                situation_id=s.id,
            )
        return sent_any

    async def _send(self, target: str, title: str, message: str, data: dict[str, Any] | None) -> None:
        domain, _, name = target.partition(".")
        if domain != "notify":
            raise ValueError(f"Not a notify target: {target}")
        if self.hass.states.get(target) is not None:  # a notify entity
            await self.hass.services.async_call(
                "notify", "send_message", {"entity_id": target, "title": title, "message": message}, blocking=True
            )
            return
        payload: dict[str, Any] = {"title": title, "message": message}
        if data:
            payload["data"] = data
        await self.hass.services.async_call("notify", name, payload, blocking=True)

    def _persistent(self, s: Situation) -> None:
        title, message = self.message(s)
        persistent_notification.async_create(
            self.hass, message, title=title, notification_id=f"{PERSISTENT_PREFIX}{s.id}"
        )
        s.notify["persistent"] = True

    def _event(self, s: Situation, step: dict[str, Any]) -> None:
        title, message = self.message(s)
        self.hass.bus.async_fire(
            EVENT_NOTIFICATION,
            {
                "situation_id": s.id,
                "title": title,
                "message": message,
                "severity": s.severity,
                "category": s.category,
                "kind": s.kind,
                "state": "active",
                "critical": bool(step.get("critical")),
            },
        )
        s.notify["event"] = True

    async def _speak(self, s: Situation) -> bool:
        tts = self.rt.settings.get("notify.tts_entity")
        players = list(self.rt.settings.get("notify.tts_players"))
        if not tts or not players or not self.hass.services.has_service("tts", "speak"):
            return False
        title, message = self.message(s)
        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {"entity_id": tts, "media_player_entity_id": players, "message": f"{title}. {message}"},
                blocking=False,
            )
        except Exception as err:
            LOGGER.warning("Speech notification failed: %s", err)
            return False
        return True

    # ——— Clearing ———
    async def clear(self, s: Situation, event: str) -> None:
        for target in s.notify.get("targets", []):
            if self.hass.states.get(target) is not None:
                continue  # notify entities have no “clear”
            try:
                await self._send(target, "", "clear_notification", {"tag": f"homeai_{s.id}"})
            except Exception as err:
                LOGGER.debug("Clearing notification on %s failed: %s", target, err)
        if s.notify.get("persistent"):
            persistent_notification.async_dismiss(self.hass, f"{PERSISTENT_PREFIX}{s.id}")
        if s.notify.get("event"):
            self.hass.bus.async_fire(
                EVENT_NOTIFICATION,
                {"situation_id": s.id, "state": "cleared", "reason": event, "title": "", "message": ""},
            )
        if event == "resolved" and s.notify.get("targets") and self.rt.settings.get("notify.announce_resolved"):
            title = self.rt.text("notify|resolved_title")
            for target in s.notify.get("targets", []):
                try:
                    await self._send(target, title, s.title(self.rt.language), {"tag": f"homeai_{s.id}_resolved"})
                except Exception as err:
                    LOGGER.debug("Resolved notice to %s failed: %s", target, err)
        if event in ("acknowledged", "handled", "snoozed"):
            return
        s.notify["targets"] = []

    # ——— Actions from phones ———
    @callback
    def _on_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        if not action.startswith(ACTION_PREFIX):
            return
        verb, _, situation_id = action[len(ACTION_PREFIX) :].partition("_")
        if verb not in ACTIONS or not situation_id:
            return
        self.hass.async_create_task(self._handle_action(verb, situation_id, event.context.user_id))

    async def _handle_action(self, verb: str, situation_id: str, user_id: str | None) -> None:
        engine = self.rt.module("situations")
        who = self.person_name(user_id)
        if verb == "ACK":
            await engine.acknowledge(situation_id, who)
        elif verb == "HANDLE":
            await engine.handle(situation_id, who)
        elif verb == "SNOOZE":
            await engine.snooze(situation_id, int(self.rt.settings.get("notify.snooze_minutes")), who)

    def person_name(self, user_id: str | None) -> str:
        if user_id:
            for p in self.rt.world.persons.values():
                if p.user_id == user_id:
                    return p.name
        return "?"

    # ——— Digest ———
    def _setup_digest(self) -> None:
        for unsub in self._digest_unsubs:
            unsub()
        self._digest_unsubs.clear()
        if not self.rt.settings.get("notify.digest_enabled"):
            return
        for value in self.rt.settings.get("notify.digest_times"):
            try:
                t = parse_time(value)
            except ValueError:
                continue
            self._digest_unsubs.append(
                async_track_time_change(self.hass, self._digest, hour=t.hour, minute=t.minute, second=0)
            )

    async def _digest(self, now: datetime) -> None:
        await self.send_digest(now)

    def digest_text(self, now: datetime | None = None) -> str | None:
        engine = self.rt.module("situations")
        items = [s for s in engine.open() if s.severity >= 1 and not s.muted(now)]
        if not items:
            return None
        lang = self.rt.language
        lines = [f"• {s.title(lang)}" for s in items[: int(self.rt.settings.get("notify.digest_max_items"))]]
        return "\n".join(lines)

    async def send_digest(self, now: datetime | None = None) -> bool:
        now = now or dt_util.utcnow()
        text = self.digest_text(now)
        ai = self.rt.module("ai")
        if text is None:
            return False
        if ai is not None:
            try:
                better = await ai.narrate_digest(text)
                if better:
                    text = better
            except Exception as err:
                LOGGER.debug("AI digest failed: %s", err)
        title = self.rt.text("notify|digest_title")
        people = [p for p in self.recipients(str(self.rt.settings.get("notify.digest_to")), now) if not p.sleep.asleep]
        sent = False
        for person in people:
            for target in targets_for(self.hass, self.rt.settings, person.entity_id):
                try:
                    await self._send(target, title, text, {"tag": "homeai_digest", "group": "homeai"})
                    sent = True
                except Exception as err:
                    LOGGER.debug("Digest to %s failed: %s", target, err)
        if sent:
            self.rt.journal.add("notification", self.rt.text("journal|digest_sent"))
        return sent
