"""Executor: the only way HomeAI changes anything in the home.

Every action goes through the same steps: validate, decide by policy, pick the right context (the person who
asked, or the HomeAI user), snapshot for undo (R1–R2), call with a timeout, verify the expected state, write
the HomeAI journal and Home Assistant's logbook ("HomeAI: …"), and fire `homeai_action`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util, ulid as ulid_util

from ..const import DOMAIN, EVENT_ACTION, LOGGER
from ..policy import ActionRequest, Decision, Risk, Verdict

# service → states that mean it worked (only where the meaning is unambiguous)
EXPECTED: dict[str, tuple[str, ...]] = {
    "open_cover": ("open", "opening"),
    "close_cover": ("closed", "closing"),
    "lock": ("locked", "locking"),
    "unlock": ("unlocked", "unlocking", "open", "opening"),
    "open": ("open", "opening", "unlocked"),
    "open_valve": ("open", "opening"),
    "close_valve": ("closed", "closing"),
    "media_play": ("playing", "buffering"),
    "media_pause": ("paused", "idle", "off"),
    "alarm_arm_away": ("armed_away", "arming", "pending"),
    "alarm_arm_home": ("armed_home", "arming", "pending"),
    "alarm_arm_night": ("armed_night", "arming", "pending"),
    "alarm_disarm": ("disarmed",),
    "return_to_base": ("returning", "docked"),
    "start": ("cleaning", "mowing"),
}
ON_OFF_DOMAINS = frozenset(
    {
        "light",
        "switch",
        "fan",
        "input_boolean",
        "siren",
        "humidifier",
        "automation",
        "remote",
        "climate",
        "water_heater",
    }
)
UNDO_PREFIX = "homeai_undo_"


@dataclass(slots=True)
class ActionResult:
    status: str  # done unverified failed denied pending_approval needs_confirmation observed would_run blocked invalid
    risk: int
    message: str = ""
    action_id: str | None = None
    approval_id: str | None = None
    undo: bool = False
    decision: dict[str, Any] = field(default_factory=dict)
    data: Any = None  # what a read or configuration operation returned

    @property
    def ok(self) -> bool:
        return self.status in ("done", "unverified", "would_run")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Executor:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass: HomeAssistant = runtime.hass
        self.recent: deque[dict[str, Any]] = deque(maxlen=100)
        self._undo: dict[str, str] = {}  # action id → scene entity
        self._config_undo: dict[str, tuple[str, dict[str, Any], Any]] = {}  # action id → (operation, data, previous)
        from .config import ConfigEditor

        self.config = ConfigEditor(runtime)

    async def async_setup(self) -> None:
        return None

    async def async_unload(self) -> None:
        return None

    # ——— Targets ———
    def targets(self, request: ActionRequest) -> list[str]:
        """Entity ids the request touches, including those named in data and area/device targets."""
        ids: list[str] = list(request.entity_ids)
        data = request.data
        for key in ("entity_id",):
            value = data.get(key)
            if isinstance(value, str) and value not in ("all", "none"):
                ids += [v.strip() for v in value.split(",") if v.strip()]
            elif isinstance(value, list):
                ids += [v for v in value if isinstance(v, str)]
        world = self.rt.world
        for area in _as_list(data.get("area_id")):
            ids += [e for e in world.in_area(area) if e.split(".", 1)[0] == request.domain]
        for device in _as_list(data.get("device_id")):
            ids += [e for e in world.of_device(device) if e.split(".", 1)[0] == request.domain]
        return list(dict.fromkeys(ids))

    def describe(self, request: ActionRequest) -> str:
        if request.domain == "config":
            subject = request.data.get("id") or request.data.get("name") or request.data.get("domain") or ""
            return self.rt.text("actions|describe", service=f"config.{request.service}", targets=[str(subject) or "—"])
        names = [self.rt.world.display_name(e) for e in self.targets(request)]
        return self.rt.text("actions|describe", service=f"{request.domain}.{request.service}", targets=names or ["—"])

    # ——— Running ———
    async def execute(self, request: ActionRequest) -> ActionResult:
        policy = self.rt.module("policy")
        request.entity_ids = self.targets(request)
        problem = self._validate(request)
        if problem:
            return self._finish(request, ActionResult("invalid", int(policy.risk(request)), problem))
        decision: Decision = await policy.decide(request)
        result_base = {"risk": int(decision.risk), "decision": decision.as_dict()}
        if decision.verdict is Verdict.DENY:
            return self._finish(request, ActionResult("denied", message=decision.reason, **result_base))
        if decision.verdict is Verdict.CONFIRM:
            return ActionResult("needs_confirmation", message=decision.reason, **result_base)
        if decision.verdict is Verdict.ASK:
            learning = self.rt.module("learning")
            if learning is not None and request.actor != "person" and learning.quiet(request):
                return self._finish(request, ActionResult("denied", message="recently_refused", **result_base))
            approvals = self.rt.module("approvals")
            if approvals is None:
                return self._finish(request, ActionResult("denied", message="no_approvals", **result_base))
            approval = await approvals.create(request, decision, self.describe(request))
            return ActionResult("pending_approval", message=decision.reason, approval_id=approval["id"], **result_base)
        if decision.verdict is Verdict.OBSERVE:
            return self._finish(request, ActionResult("observed", message=decision.reason, **result_base))
        if self._offline(request):
            return self._finish(request, ActionResult("blocked", message="internet_down", **result_base))
        if request.dry_run:
            return ActionResult("would_run", message=decision.reason, **result_base)
        return await self._run(request, decision)

    def _validate(self, request: ActionRequest) -> str | None:
        if request.domain == "config":
            return None if self.config.supports(request.service) else "unknown_service"
        if not self.hass.services.has_service(request.domain, request.service):
            return "unknown_service"
        missing = [e for e in request.entity_ids if self.hass.states.get(e) is None]
        if missing:
            return f"unknown_entity:{','.join(missing)}"
        return None

    def _offline(self, request: ActionRequest) -> bool:
        """Cloud devices while the internet is down: refuse instead of failing slowly."""
        if not self.rt.settings.get("executor.block_cloud_offline"):
            return False
        hub = self.rt.module("signals")
        if hub is None or not any(s.kind == "internet_down" for s in hub.signals.values()):
            return False
        from ..signals.detectors.system import device_tags

        ctx = hub.context()
        for entity_id in request.entity_ids:
            info = self.rt.world.entity(entity_id)
            if info and info.device_id and "cloud" in device_tags(ctx, info.device_id):
                return True
        return False

    def context(self, request: ActionRequest) -> Context:
        if request.actor == "person" and request.user_id:
            return Context(user_id=request.user_id)
        return Context(user_id=self.rt.system_user_id)

    async def _run(self, request: ActionRequest, decision: Decision) -> ActionResult:
        action_id = ulid_util.ulid_now().lower()
        ctx = self.context(request)
        risk = int(decision.risk)
        if request.domain == "config":
            return await self._run_config(request, decision, action_id, ctx)
        undo = False
        if Risk.R1 <= decision.risk <= Risk.R2 and request.entity_ids and self.rt.settings.get("executor.undo"):
            undo = await self._snapshot(action_id, request.entity_ids, ctx)
        before = {e: s.state for e in request.entity_ids if (s := self.hass.states.get(e)) is not None}
        data = dict(request.data)
        if request.entity_ids and not any(k in data for k in ("entity_id", "area_id", "device_id")):
            data["entity_id"] = request.entity_ids
        timeout = float(self.rt.settings.get("executor.timeout"))
        try:
            async with asyncio.timeout(timeout):
                await self.hass.services.async_call(request.domain, request.service, data, blocking=True, context=ctx)
        except TimeoutError:
            return self._finish(
                request, ActionResult("failed", risk, "timeout", action_id, decision=decision.as_dict()), ctx
            )
        except Exception as err:
            LOGGER.warning("HomeAI action %s.%s failed: %s", request.domain, request.service, err)
            return self._finish(
                request, ActionResult("failed", risk, str(err)[:300], action_id, decision=decision.as_dict()), ctx
            )
        if request.playbook and decision.risk == Risk.R3:
            self.rt.module("policy").count_repair()
        verified = await self._verify(request, before)
        status = "done" if verified is not False else "unverified"
        result = ActionResult(status, risk, decision.reason, action_id, undo=undo, decision=decision.as_dict())
        return self._finish(request, result, ctx)

    async def _run_config(
        self, request: ActionRequest, decision: Decision, action_id: str, ctx: Context
    ) -> ActionResult:
        from .config import ConfigError

        risk = int(decision.risk)
        try:
            async with asyncio.timeout(float(self.rt.settings.get("executor.timeout"))):
                outcome = await self.config.run(request.service, request.data)
        except (ConfigError, TimeoutError) as err:
            return self._finish(
                request,
                ActionResult("failed", risk, str(err)[:300] or "timeout", action_id, decision=decision.as_dict()),
                ctx,
            )
        undo = False
        if request.service.endswith(("_save", "_delete")) and request.service.split("_", 1)[0] in (
            "automation",
            "script",
            "scene",
        ):
            self._config_undo[action_id] = (request.service, dict(request.data), outcome.get("previous"))
            undo = True
        result = ActionResult(
            "done", risk, decision.reason, action_id, undo=undo, decision=decision.as_dict(), data=outcome.get("result")
        )
        if risk == Risk.R0:
            return result  # reads are not journalled
        return self._finish(request, result, ctx)

    async def _snapshot(self, action_id: str, entity_ids: list[str], ctx: Context) -> bool:
        if not self.hass.services.has_service("scene", "create"):
            return False
        scene_id = f"{UNDO_PREFIX}{action_id}"
        try:
            await self.hass.services.async_call(
                "scene", "create", {"scene_id": scene_id, "snapshot_entities": entity_ids}, blocking=True, context=ctx
            )
        except Exception as err:
            LOGGER.debug("Undo snapshot failed: %s", err)
            return False
        self._undo[action_id] = f"scene.{scene_id}"
        keep = int(self.rt.settings.get("executor.undo_keep"))
        while len(self._undo) > keep:
            old_id = next(iter(self._undo))
            old = self._undo.pop(old_id)
            if self.hass.services.has_service("scene", "delete"):
                try:
                    await self.hass.services.async_call(
                        "scene", "delete", {"entity_id": old}, blocking=True, context=ctx
                    )
                except Exception:
                    LOGGER.debug("Removing old undo scene %s failed", old)
        return True

    def expected(self, request: ActionRequest, entity_id: str, before: str | None) -> tuple[str, ...] | None:
        domain = entity_id.split(".", 1)[0]
        service = request.service
        if service in EXPECTED:
            return EXPECTED[service]
        if domain in ON_OFF_DOMAINS or request.domain == "homeassistant":
            if service == "turn_on" and domain not in ("climate", "water_heater"):
                return ("on",)
            if service == "turn_off":
                return ("off",)
            if service == "toggle" and before in ("on", "off"):
                return ("off",) if before == "on" else ("on",)
        return None

    async def _verify(self, request: ActionRequest, before: dict[str, str]) -> bool | None:
        """True when every target reached its expected state, False when not, None when nothing to check."""
        wanted = {e: exp for e in request.entity_ids if (exp := self.expected(request, e, before.get(e)))}
        if not wanted:
            return None

        def satisfied() -> bool:
            return all((s := self.hass.states.get(e)) is not None and s.state in exp for e, exp in wanted.items())

        if satisfied():
            return True
        done = asyncio.Event()

        @callback
        def changed(_event: Event) -> None:
            if satisfied():
                done.set()

        unsub = async_track_state_change_event(self.hass, list(wanted), changed)
        try:
            async with asyncio.timeout(float(self.rt.settings.get("executor.verify_seconds"))):
                await done.wait()
        except TimeoutError:
            return satisfied()
        finally:
            unsub()
        return True

    # ——— Undo ———
    async def undo(self, action_id: str, user_id: str | None = None) -> ActionResult:
        if action_id in self._config_undo:
            return await self._undo_config(action_id, user_id)
        scene = self._undo.pop(action_id, None)
        if scene is None or self.hass.states.get(scene) is None:
            return ActionResult("invalid", 0, "nothing_to_undo", action_id)
        ctx = Context(user_id=user_id or self.rt.system_user_id)
        try:
            await self.hass.services.async_call("scene", "turn_on", {"entity_id": scene}, blocking=True, context=ctx)
        except Exception as err:
            return ActionResult("failed", 1, str(err)[:300], action_id)
        record = next((r for r in self.recent if r["action_id"] == action_id), None)
        if record is not None:
            record["undone"] = True
        self.rt.journal.add(
            "action",
            self.rt.text("journal|action_undone", what=record["what"] if record else action_id),
            actor="person" if user_id else "homeai",
            result="undone",
        )
        learning = self.rt.module("learning")
        if learning is not None and record is not None:
            learning.feedback("undo", record)
        return ActionResult("done", 1, "undone", action_id)

    async def _undo_config(self, action_id: str, user_id: str | None) -> ActionResult:
        """Configuration changes are undone only by an administrator (or HomeAI itself)."""
        from .config import ConfigError

        user = await self.hass.auth.async_get_user(user_id) if user_id else None
        if user is not None and not user.is_admin:
            return ActionResult("denied", 4, "admin_required", action_id)
        operation, data, previous = self._config_undo.pop(action_id)
        try:
            await self.config.restore(operation, data, previous)
        except ConfigError as err:
            return ActionResult("failed", 4, str(err)[:300], action_id)
        record = next((r for r in self.recent if r["action_id"] == action_id), None)
        if record is not None:
            record["undone"] = True
        self.rt.journal.add(
            "action",
            self.rt.text("journal|action_undone", what=record["what"] if record else action_id),
            actor="person" if user_id else "homeai",
            result="undone",
        )
        return ActionResult("done", 4, "undone", action_id)

    # ——— Audit ———
    def _finish(self, request: ActionRequest, result: ActionResult, ctx: Context | None = None) -> ActionResult:
        what = self.describe(request)
        record = {
            "action_id": result.action_id,
            "ts": dt_util.utcnow().isoformat(timespec="seconds"),
            "what": what,
            "request": request.as_dict(),
            "result": result.as_dict(),
            "undone": False,
        }
        self.recent.appendleft(record)
        key = {
            "done": "action_done",
            "unverified": "action_unverified",
            "failed": "action_failed",
            "denied": "action_denied",
            "observed": "action_observed",
            "blocked": "action_blocked",
            "invalid": "action_failed",
        }.get(result.status, "action_done")
        text = self.rt.text(f"journal|{key}", what=what, reason=result.message)
        self.rt.journal.add(
            "action",
            text,
            actor=request.actor,
            situation_id=request.situation_id,
            result=result.status,
            data={"risk": result.risk, "action_id": result.action_id, "reason": request.reason},
        )
        if result.status in ("done", "unverified", "failed") and "logbook" in self.hass.config.components:
            from homeassistant.components.logbook import async_log_entry

            async_log_entry(
                self.hass,
                "HomeAI",
                text,
                DOMAIN,
                request.entity_ids[0] if request.entity_ids else None,
                ctx,
            )
        self.hass.bus.async_fire(
            EVENT_ACTION,
            {
                "action_id": result.action_id,
                "status": result.status,
                "risk": result.risk,
                "what": what,
                "actor": request.actor,
                "situation_id": request.situation_id,
                "entities": request.entity_ids,
            },
            context=ctx,
        )
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {"recent": list(self.recent)[:20], "undo": list(self._undo), "config_undo": list(self._config_undo)}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []
