"""Provider adapters: request shape and response parsing, without network calls."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeai.ai.pricing import price_for
from custom_components.homeai.ai.providers.anthropic import AnthropicProvider
from custom_components.homeai.ai.providers.base import AIError, AIRequest, ToolCall, ToolSpec
from custom_components.homeai.ai.providers.openai_compat import OpenAICompatProvider
from custom_components.homeai.const import DOMAIN

from .common import setup_homeai
from .home import standard_home


class Block(SimpleNamespace):
    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class FakeMessages:
    def __init__(self, message: Any) -> None:
        self.message = message
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> Any:
        self.params = params
        return self.message


class FakeClient:
    def __init__(self, message: Any) -> None:
        self.messages = FakeMessages(message)
        self.beta = SimpleNamespace(messages=self.messages)

    def with_options(self, **_kw: Any) -> FakeClient:
        return self


def message(content: list[Block], stop: str = "end_turn") -> Any:
    usage = SimpleNamespace(
        input_tokens=1000, output_tokens=200, cache_read_input_tokens=5000, cache_creation_input_tokens=0
    )
    return SimpleNamespace(content=content, stop_reason=stop, model="claude-opus-5-5", usage=usage)


async def test_anthropic_request_and_structured_answer() -> None:
    client = FakeClient(message([Block(type="thinking", thinking=""), Block(type="text", text='{"severity": 2}')]))
    provider = AnthropicProvider(client, "claude-opus-5-5", price_for("claude-opus-5-5"))
    response = await provider.complete(
        AIRequest(
            system="sys", messages=[{"role": "user", "content": "hi"}], schema={"type": "object"}, effort="medium"
        )
    )
    params = client.messages.params
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert params["betas"] == ["server-side-fallback-2026-07-01"] and params["fallbacks"] == "default"
    assert "thinking" not in params and "temperature" not in params
    assert response.data == {"severity": 2}
    # 1000 × $4 + 200 × $20 + 5000 × $0.20 per million
    assert response.cost == pytest.approx((1000 * 4 + 200 * 20 + 5000 * 0.2) / 1e6)
    assert response.assistant_message["content"][0]["type"] == "thinking"


async def test_anthropic_tools_refusal_and_haiku_without_fallbacks() -> None:
    client = FakeClient(
        message([Block(type="tool_use", id="t1", name="get_state", input={"entity_id": "light.a"})], "tool_use")
    )
    provider = AnthropicProvider(client, "claude-haiku-5-5", price_for("claude-haiku-5-5"))
    response = await provider.complete(
        AIRequest(
            system="s",
            messages=[{"role": "user", "content": "x"}],
            tools=[ToolSpec("get_state", "Read a state", {"type": "object", "properties": {}})],
        )
    )
    assert "fallbacks" not in client.messages.params  # Haiku has no server-side fallback
    assert response.tool_calls == [ToolCall("t1", "get_state", {"entity_id": "light.a"})]
    results = provider.tool_results([(response.tool_calls[0], "on", False)])
    assert results == [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "on", "is_error": False}]}
    ]

    refusing = AnthropicProvider(FakeClient(message([], "refusal")), "claude-opus-5-5", price_for("claude-opus-5-5"))
    with pytest.raises(AIError) as err:
        await refusing.complete(AIRequest(system="s", messages=[{"role": "user", "content": "x"}]))
    assert err.value.refusal


async def test_openai_compatible(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post(
        "http://ollama.local:11434/v1/chat/completions",
        json={
            "model": "qwen3:4b",
            "choices": [
                {"message": {"role": "assistant", "content": '```json\n{"severity": 1}\n```'}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 300, "completion_tokens": 40},
        },
    )
    aioclient_mock.get("http://ollama.local:11434/v1/models", json={"data": [{"id": "qwen3:4b"}]})
    provider = OpenAICompatProvider(hass, "http://ollama.local:11434/v1/", "qwen3:4b", price_for("qwen3:4b"))
    await provider.check()
    response = await provider.complete(
        AIRequest(
            system="sys", messages=[{"role": "user", "content": "hi"}], schema={"type": "object"}, purpose="triage"
        )
    )
    assert response.data == {"severity": 1} and response.cost == 0 and response.input_tokens == 300
    sent = aioclient_mock.mock_calls[-1][2]
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["response_format"]["json_schema"]["name"] == "triage"


async def test_openai_compatible_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.post("http://x/v1/chat/completions", status=401, json={})
    aioclient_mock.get("http://x/v1/models", json={"data": [{"id": "other"}]})
    provider = OpenAICompatProvider(hass, "http://x/v1", "qwen", price_for("qwen"))
    with pytest.raises(AIError, match="invalid_auth"):
        await provider.complete(AIRequest(system="s", messages=[{"role": "user", "content": "x"}]))
    with pytest.raises(AIError, match="unknown_model"):
        await provider.check()


async def test_tier_subentry_flow(hass: HomeAssistant) -> None:
    standard_home(hass)
    rt = await setup_homeai(hass)
    entry = rt.entry
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tier"), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"tier": "p2", "provider": "anthropic"}
    )
    assert result["step_id"] == "details"
    with patch("custom_components.homeai.ai.subentry.validate", return_value="invalid_auth"):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                "api_key": "bad",
                "model": "claude-opus-5-5",
                "effort": "medium",
                "fallbacks": True,
                "privacy": "default",
                "priority": 1,
            },
        )
    assert result["errors"] == {"base": "invalid_auth"}
    with patch("custom_components.homeai.ai.subentry.validate", return_value=None):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                "api_key": "sk-good",
                "model": "claude-opus-5-5",
                "effort": "medium",
                "fallbacks": True,
                "privacy": "default",
                "priority": 1,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    [sub] = entry.subentries.values()
    assert sub.data["tier"] == "p2" and sub.title == "P2 · claude-opus-5-5"
    # adding a tier reloads HomeAI, which now knows the tier
    assert entry.runtime_data.module("ai").tiers["p2"][0].model == "claude-opus-5-5"


async def test_diagnostics_redact_keys(hass: HomeAssistant) -> None:
    from custom_components.homeai.diagnostics import async_get_config_entry_diagnostics

    standard_home(hass)
    await setup_homeai(
        hass, subentries=[{"tier": "p1", "provider": "anthropic", "model": "claude-haiku-5-5", "api_key": "sk-secret"}]
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "sk-secret" not in str(diag)
