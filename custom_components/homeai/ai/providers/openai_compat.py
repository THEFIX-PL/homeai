"""OpenAI-compatible chat completions: Ollama, llama.cpp server, vLLM, LM Studio, OpenRouter and others.

Used for local models (e.g. a small Qwen as the home's everyday brain). Talks HTTP through Home Assistant's
shared aiohttp session; no extra dependency.
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..pricing import Price
from .base import AIError, AIRequest, AIResponse, ToolCall

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class OpenAICompatProvider:
    name = "openai_compatible"

    def __init__(self, hass: HomeAssistant, base_url: str, model: str, price: Price, api_key: str = "") -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.price = price
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def check(self) -> None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status in (401, 403):
                    raise AIError("invalid_auth", retryable=False)
                if resp.status >= 400:
                    raise AIError(f"api_error:{resp.status}")
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AIError("cannot_connect") from err
        models = {m.get("id") for m in (body or {}).get("data", []) if isinstance(m, dict)}
        if models and self.model not in models:
            raise AIError("unknown_model", retryable=False)

    def _messages(self, request: AIRequest) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        for m in request.messages:
            if isinstance(m.get("content"), str) or m.get("role") == "tool" or "tool_calls" in m:
                out.append(m)
            else:  # vendor-neutral list content → plain text
                text = "\n".join(str(b.get("text", "")) for b in m["content"] if isinstance(b, dict))
                out.append({"role": m["role"], "content": text})
        return out

    async def complete(self, request: AIRequest) -> AIResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(request),
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.purpose or "answer", "schema": request.schema, "strict": True},
            }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
                }
                for t in request.tools
            ]
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=request.timeout),
            ) as resp:
                body = await resp.json(content_type=None)
                if resp.status in (401, 403):
                    raise AIError("invalid_auth", retryable=False)
                if resp.status == 429:
                    raise AIError("rate_limited")
                if resp.status >= 400:
                    raise AIError(f"api_error:{resp.status}", retryable=resp.status >= 500)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AIError("cannot_connect") from err
        except ValueError as err:
            raise AIError("bad_response") from err
        return self._response(body, request)

    def _response(self, body: dict[str, Any], request: AIRequest) -> AIResponse:
        try:
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as err:
            raise AIError("bad_response") from err
        usage = body.get("usage") or {}
        out = AIResponse(
            text=str(message.get("content") or "").strip(),
            stop_reason=str(choice.get("finish_reason") or ""),
            model=str(body.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            provider=self.name,
        )
        out.cost = self.price.cost(out.input_tokens, out.output_tokens)
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            out.tool_calls.append(
                ToolCall(str(call.get("id")), str(fn.get("name")), args if isinstance(args, dict) else {})
            )
        out.assistant_message = {k: v for k, v in message.items() if k in ("role", "content", "tool_calls")}
        if request.schema is not None and not out.tool_calls:
            try:
                out.data = json.loads(FENCE.sub("", out.text))
            except ValueError as err:
                raise AIError("bad_json") from err
        return out

    def tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> list[dict[str, Any]]:
        return [{"role": "tool", "tool_call_id": c.id, "content": text} for c, text, _ in results]
