"""A scripted AI provider for tests."""

from __future__ import annotations

from typing import Any

from custom_components.homeai.ai.providers.base import AIError, AIRequest, AIResponse


class FakeProvider:
    name = "fake"

    def __init__(self, answers: list[Any] | None = None, model: str = "fake-model", cost: float = 0.001) -> None:
        self.answers = list(answers or [])
        self.model = model
        self.cost = cost
        self.requests: list[AIRequest] = []

    async def check(self) -> None:
        return None

    async def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else {"text": "ok"}
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, dict) and "text" in answer:
            return AIResponse(text=answer["text"], model=self.model, cost=self.cost, input_tokens=100, output_tokens=20)
        return AIResponse(data=answer, text="{}", model=self.model, cost=self.cost, input_tokens=100, output_tokens=20)

    def tool_results(self, results):  # pragma: no cover - not used here
        return []


def tier(t: str = "p1", model: str = "claude-haiku-5-5", **kw: Any) -> dict[str, Any]:
    return {"tier": t, "provider": "anthropic", "model": model, "api_key": "sk-test", **kw}


def install(rt: Any, tier_name: str, provider: FakeProvider, index: int = 0) -> None:
    cfg = rt.module("ai").tiers[tier_name][index]
    rt.module("ai")._providers[cfg.subentry_id] = provider


__all__ = ["AIError", "FakeProvider", "install", "tier"]
