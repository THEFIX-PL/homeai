"""The AI stage: tiers from subentries, one `ask` path with budgets, privacy and fallbacks, and the missions.

Code decides first; AI refines. Nothing here can act in the home: missions return assessments and texts, and
anything that would change the home goes through the executor and its policy (later stages give P2 tools).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import LOGGER
from ..situations.model import Phase, Situation
from .budget import Ledger
from .missions.investigate import investigate
from .missions.triage import needs_triage, run_triage
from .privacy import Privacy
from .prompts import DIGEST
from .providers.base import AIError, AIRequest, AIResponse, Provider
from .tiers import TierConfig, build_provider

TIER_TIMEOUT = {"p1": "ai.timeout", "p2": "ai.timeout", "p3": "ai.p3_timeout"}


class AIModule:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self.ledger = Ledger(runtime)
        self.tiers: dict[str, list[TierConfig]] = {}
        self._providers: dict[str, Provider] = {}
        self._calls: deque[tuple[str, Any]] = deque(maxlen=1000)  # (tier, time) for the hourly limit
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._unsubs: list[Callable[[], None]] = []
        self.last_prompts: dict[str, dict[str, Any]] = {}
        self.status: dict[str, str] = {}  # subentry id → "ok" | error code
        self.threads: dict[str, dict[str, Any]] = {}  # conversation id → chat thread

    async def async_setup(self) -> None:
        await self.ledger.async_load()
        self.tiers = {}
        for sid, sub in self.rt.entry.subentries.items():
            if sub.subentry_type != "tier":
                continue
            cfg = TierConfig.from_data(sid, dict(sub.data), sub.title)
            self.tiers.setdefault(cfg.tier, []).append(cfg)
        for configs in self.tiers.values():
            configs.sort(key=lambda c: c.priority)
        engine = self.rt.module("situations")
        if engine is not None:
            self._unsubs.append(engine.listen(self._on_situation))
        from homeassistant.helpers import llm

        from .llm_api import HomeAIAPI

        try:
            self._unsubs.append(llm.async_register_api(self.hass, HomeAIAPI(self.hass, self.rt)))
        except Exception:
            LOGGER.exception("Registering the HomeAI LLM API failed")

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        for task in list(self._tasks):
            task.cancel()
        await self.ledger.async_save()

    # ——— Tiers ———
    def enabled(self) -> bool:
        return bool(self.rt.settings.get("ai.enabled"))

    def available(self, tier: str) -> bool:
        return self.enabled() and bool(self.tiers.get(tier))

    def first(self, tier: str) -> TierConfig | None:
        configs = self.tiers.get(tier) or []
        return configs[0] if configs and self.enabled() else None

    def privacy_level(self, cfg: TierConfig) -> str:
        return (
            cfg.privacy
            if cfg.privacy in ("minimal", "standard", "full")
            else str(self.rt.settings.get("privacy.level"))
        )

    async def provider(self, cfg: TierConfig) -> Provider:
        if cfg.subentry_id not in self._providers:
            self._providers[cfg.subentry_id] = await build_provider(self.hass, cfg)
        return self._providers[cfg.subentry_id]

    def _rate_ok(self, tier: str) -> bool:
        limit = int(self.rt.settings.get("ai.max_calls_per_hour"))
        since = dt_util.utcnow() - timedelta(hours=1)
        return sum(1 for t, at in self._calls if t == tier and at > since) < limit

    # ——— Asking ———
    async def ask(
        self, tier: str, request: AIRequest, *, situation_id: str | None = None, only: str | None = None
    ) -> AIResponse | None:
        """Ask a tier; tries its providers in order. None when AI is off, over budget or every provider failed."""
        if not self.available(tier):
            return None
        if not self.ledger.allowed():
            LOGGER.debug("AI budget exhausted; %s skipped", request.purpose)
            return None
        if not self._rate_ok(tier):
            LOGGER.debug("AI hourly limit reached for %s", tier)
            return None
        request.timeout = float(self.rt.settings.get(TIER_TIMEOUT.get(tier, "ai.timeout")))
        for cfg in self.tiers.get(tier, []):
            if only is not None and cfg.subentry_id != only:
                continue  # a tool loop stays with the provider that started it
            if request.effort is None and cfg.effort:
                request.effort = cfg.effort
            try:
                provider = await self.provider(cfg)
                self._calls.append((tier, dt_util.utcnow()))
                response = await provider.complete(request)
            except AIError as err:
                self.status[cfg.subentry_id] = str(err)
                LOGGER.warning("AI %s (%s) failed for %s: %s", tier, cfg.model, request.purpose, err)
                continue  # the next provider of this tier may still answer
            except Exception:
                self.status[cfg.subentry_id] = "error"
                LOGGER.exception("AI %s (%s) crashed for %s", tier, cfg.model, request.purpose)
                continue
            self.status[cfg.subentry_id] = "ok"
            response.source = cfg.subentry_id
            self.ledger.record(
                tier, response.model, response.cost, response.input_tokens, response.output_tokens, request.purpose
            )
            if self.rt.settings.get("privacy.log_prompts"):
                self.last_prompts[tier] = {
                    "ts": dt_util.utcnow().isoformat(timespec="seconds"),
                    "provider": cfg.provider,
                    "model": response.model,
                    "purpose": request.purpose,
                    "system": request.system,
                    "messages": request.messages[-3:],
                    "answer": response.text[:4000],
                    "cost": response.cost,
                }
            return response
        return None

    # ——— Situations ———
    def _on_situation(self, event: str, s: Situation) -> None:
        if event not in ("opened", "updated") or s.phase is not Phase.OPEN or s.id in self._busy:
            return
        if not self.available("p1") or not needs_triage(self.rt, s):
            return
        self._busy.add(s.id)
        task = self.hass.async_create_background_task(self._triage(s), f"homeai triage {s.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _triage(self, s: Situation) -> None:
        try:
            await self.triage(s)
        finally:
            self._busy.discard(s.id)

    async def triage(self, s: Situation) -> dict[str, Any] | None:
        """P1, then P2 when P1 is unsure or the matter is serious; a disagreement is marked for the arbiter."""
        settings = self.rt.settings
        triage = self.rt.module("triage")
        engine = self.rt.module("situations")
        before = (s.severity, s.assessment.get("who"))
        p1 = await run_triage(self, s, "p1")
        result, tier = p1, "p1"
        if p1 is not None:
            s.log("ai_assessed", tier="p1", severity=p1["severity"], who=p1["who"], confidence=p1["confidence"])
        dispute: dict[str, Any] | None = None
        need_p2 = (
            p1 is None
            or p1["confidence"] < float(settings.get("ai.p2_confidence"))
            or (p1["severity"] >= int(settings.get("ai.p2_min_severity")))
        )
        if need_p2 and self.available("p2"):
            p2 = await investigate(self, s)
            if p2 is not None:
                s.log("ai_assessed", tier="p2", severity=p2["severity"], who=p2["who"], confidence=p2["confidence"])
                if p1 is not None and (abs(p1["severity"] - p2["severity"]) >= 2 or p1["who"] != p2["who"]):
                    dispute = {"p1": p1, "p2": p2}
                result, tier = p2, "p2"
        if result is None or s.phase is not Phase.OPEN:
            return None
        triage.apply_ai(s, result, tier)
        if dispute is not None:
            s.assessment["dispute"] = dispute
            arbiter = self.rt.module("arbiter")
            if arbiter is not None:
                arbiter.queue_dispute(s)
        self.rt.journal.add(
            "ai",
            self.rt.text(
                "journal|ai_assessed",
                title=s.title(self.rt.language),
                tier=tier.upper(),
                severity=result["severity"],
                reason=result["reason"],
            ),
            situation_id=s.id,
        )
        if (s.severity, s.assessment.get("who")) != before:
            await engine.reassessed(s)
        else:
            engine.save()
        return result

    # ——— Conversations ———
    async def chat(self, text: str, conversation_id: str, user_id: str | None) -> tuple[str, list[dict[str, Any]]]:
        from .missions.chat import chat

        return await chat(self, text, conversation_id, user_id)

    # ——— Digest ———
    async def narrate_digest(self, text: str) -> str | None:
        if not self.rt.settings.get("ai.narrate_digest") or not self.available("p1"):
            return None
        cfg = self.first("p1")
        if cfg is None or self.privacy_level(cfg) == "minimal":
            return None  # the list carries real names and rooms
        privacy = Privacy(self.rt, self.privacy_level(cfg))
        from .privacy import clean

        request = AIRequest(
            system=DIGEST,
            messages=[
                {
                    "role": "user",
                    "content": f"Language: {self.rt.language}\n<open_matters>\n{clean(text, 4000)}\n</open_matters>",
                }
            ],
            max_tokens=1024,
            purpose="digest",
        )
        response = await self.ask("p1", request)
        if response is None or not response.text:
            return None
        return privacy.restore(response.text)[:1200]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "tiers": {
                t: [
                    {
                        "model": c.model,
                        "provider": c.provider,
                        "priority": c.priority,
                        "status": self.status.get(c.subentry_id),
                    }
                    for c in cs
                ]
                for t, cs in self.tiers.items()
            },
            "ledger": self.ledger.summary(),
        }
