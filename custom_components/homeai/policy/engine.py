"""The policy: may this action run now, does it need someone's approval, or is it refused?

Actors:
- `person`: a resident asked for it; it runs in their Home Assistant user context, so HA permissions apply.
  R0–R1 run; R2 runs or asks the person to confirm (`policy.person_r2`); R3–R4 need an administrator;
  R5 needs the person's explicit confirmation; R6 needs an administrator's explicit confirmation.
- `homeai` (autonomy), `ai`, `repair`, `schedule`: run as the HomeAI user. Each class has a level
  (`policy.autonomy_r1` … `policy.autonomy_r4`): never → observe → propose → act and tell → act.
  R5 and R6 are never autonomous, except protective actions on entities the administrator labelled.
  Repairs may only run R3 actions from playbooks, within the daily limit. Schedule entries run up to the
  class their author approved. During the first `policy.observation_days` R1–R2 autonomy only observes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from homeassistant.util import dt as dt_util

from .risk import Risk, classify, is_protective

ACTORS = ("person", "homeai", "ai", "repair", "schedule")
LEVELS = ("never", "observe", "propose", "act_tell", "act")


class Verdict(StrEnum):
    ALLOW = "allow"  # run now
    CONFIRM = "confirm"  # the requesting person must confirm explicitly
    ASK = "ask"  # someone else must approve (residents for R1–R2, administrators for R3+)
    OBSERVE = "observe"  # record what would have been done, do nothing
    DENY = "deny"


@dataclass(slots=True)
class ActionRequest:
    domain: str
    service: str
    data: dict[str, Any] = field(default_factory=dict)
    entity_ids: list[str] = field(default_factory=list)
    actor: str = "homeai"
    user_id: str | None = None
    reason: str = ""
    situation_id: str | None = None
    playbook: str | None = None
    approved_risk: int | None = None  # schedule entries: the class approved by their author
    confirmed: bool = False  # the person confirmed (R5/R6, or R2 when asked)
    approved_by: str | None = None  # an approval was granted
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionRequest:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(slots=True)
class Decision:
    verdict: Verdict
    risk: Risk
    reason: str
    approver: str | None = None  # "residents" or "admins" when verdict is ASK
    tell: bool = False  # notify people after acting (level act_tell, protective actions)
    protective: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict),
            "risk": int(self.risk),
            "reason": self.reason,
            "approver": self.approver,
            "tell": self.tell,
            "protective": self.protective,
        }


class Policy:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self._repairs_today: tuple[str, int] = ("", 0)

    async def async_setup(self) -> None:
        return None

    async def async_unload(self) -> None:
        return None

    # ——— Classification ———
    def risk(self, request: ActionRequest) -> Risk:
        return classify(
            request.domain, request.service, request.entity_ids, world=self.rt.world, settings=self.rt.settings
        )

    def observing(self, now: datetime | None = None) -> bool:
        days = int(self.rt.settings.get("policy.observation_days"))
        installed = dt_util.parse_datetime(self.rt.installed_at) if self.rt.installed_at else None
        if not days or installed is None:
            return False
        return (now or dt_util.utcnow()) < installed + timedelta(days=days)

    def level(self, risk: Risk) -> str:
        if risk == Risk.R0:
            return "act"
        if risk >= Risk.R5:
            return "never"
        return str(self.rt.settings.get(f"policy.autonomy_r{int(risk)}"))

    # ——— Decision ———
    async def decide(self, request: ActionRequest, now: datetime | None = None) -> Decision:
        risk = self.risk(request)
        if request.actor == "person":
            return await self._person(request, risk)
        return self._autonomous(request, risk, now)

    async def _person(self, request: ActionRequest, risk: Risk) -> Decision:
        user = await self.rt.hass.auth.async_get_user(request.user_id) if request.user_id else None
        if user is None and not request.user_id and risk <= Risk.R1:
            return Decision(Verdict.ALLOW, risk, "anonymous")  # e.g. a voice satellite without a user
        if user is None or not user.is_active:
            return Decision(Verdict.DENY, risk, "no_user")
        admin = user.is_admin
        if risk <= Risk.R1:
            return Decision(Verdict.ALLOW, risk, "person")
        if risk == Risk.R2:
            if self.rt.settings.get("policy.person_r2") == "act" or request.confirmed:
                return Decision(Verdict.ALLOW, risk, "person")
            return Decision(Verdict.CONFIRM, risk, "person_confirm")
        if risk in (Risk.R3, Risk.R4):
            if not admin:
                return Decision(Verdict.ASK, risk, "admin_required", approver="admins")
            return Decision(Verdict.ALLOW if request.confirmed or risk == Risk.R3 else Verdict.CONFIRM, risk, "admin")
        if risk == Risk.R5:
            return Decision(Verdict.ALLOW if request.confirmed else Verdict.CONFIRM, risk, "security_confirm")
        if not admin:
            return Decision(Verdict.DENY, risk, "admin_required")
        return Decision(Verdict.ALLOW if request.confirmed else Verdict.CONFIRM, risk, "destructive_confirm")

    def _autonomous(self, request: ActionRequest, risk: Risk, now: datetime | None) -> Decision:
        world = self.rt.world
        if request.approved_by:
            # an approval was granted: administrators for R3+, any resident for R1–R2; never R6
            if risk >= Risk.R6:
                return Decision(Verdict.DENY, risk, "never_autonomous")
            return Decision(Verdict.ALLOW, risk, "approved", tell=True)
        if risk == Risk.R0:
            return Decision(Verdict.ALLOW, risk, "read")
        if is_protective(request.domain, request.service, request.entity_ids, world) and self.rt.settings.get(
            "policy.protective_actions"
        ):
            return Decision(Verdict.ALLOW, risk, "protective", tell=True, protective=True)
        if risk >= Risk.R5:
            return Decision(Verdict.DENY, risk, "never_autonomous")
        if request.actor == "schedule":
            approved = Risk.parse(request.approved_risk)
            if approved is not None and risk <= approved:
                return Decision(Verdict.ALLOW, risk, "schedule")
            return Decision(Verdict.ASK, risk, "schedule_above_approved", approver=_approver(risk))
        if risk == Risk.R3:
            if request.actor != "repair" or not request.playbook:
                return Decision(Verdict.ASK, risk, "system_needs_playbook", approver="admins")
            if not self._repair_budget(now):
                return Decision(Verdict.ASK, risk, "repair_limit", approver="admins")
        level = self.level(risk)
        if risk in (Risk.R1, Risk.R2) and self.observing(now) and level in ("act", "act_tell"):
            level = "observe"
        learning = self.rt.module("learning")
        if level in ("act", "act_tell") and learning is not None and learning.restricted(request):
            level = "propose"  # people undid this too often
        if level == "never":
            return Decision(Verdict.DENY, risk, "level_never")
        if level == "observe":
            return Decision(Verdict.OBSERVE, risk, "observing")
        if level == "propose":
            return Decision(Verdict.ASK, risk, "propose", approver=_approver(risk))
        return Decision(Verdict.ALLOW, risk, f"level_{level}", tell=level == "act_tell")

    def _repair_budget(self, now: datetime | None) -> bool:
        today = dt_util.as_local(now or dt_util.utcnow()).date().isoformat()
        day, count = self._repairs_today
        return not (day == today and count >= int(self.rt.settings.get("policy.repairs_per_day")))

    def count_repair(self, now: datetime | None = None) -> None:
        today = dt_util.as_local(now or dt_util.utcnow()).date().isoformat()
        day, count = self._repairs_today
        self._repairs_today = (today, (count if day == today else 0) + 1)

    def diagnostics(self) -> dict[str, Any]:
        return {"observing": self.observing(), "repairs_today": self._repairs_today}


def _approver(risk: Risk) -> str:
    return "residents" if risk <= Risk.R2 else "admins"
