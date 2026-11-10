"""Claude through the official Anthropic SDK.

- The stable system prompt is cached (`cache_control` on the system block); volatile context goes last.
- Thinking is left to the model's default (adaptive); depth is set with `output_config.effort`.
- Structured answers use `output_config.format` (JSON schema).
- Refusals: on models that support it, the server-side fallback is enabled (`fallbacks: "default"`).
"""

from __future__ import annotations

from functools import partial
import json
from typing import Any

import anthropic
from homeassistant.core import HomeAssistant

from ..pricing import Price
from .base import AIError, AIRequest, AIResponse, ToolCall

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")


async def async_create_client(hass: HomeAssistant, api_key: str) -> anthropic.AsyncAnthropic:
    """Create the client off the event loop (it loads certificates)."""
    return await hass.async_add_executor_job(partial(anthropic.AsyncAnthropic, api_key=api_key, max_retries=2))


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: anthropic.AsyncAnthropic, model: str, price: Price, *, fallbacks: bool = True) -> None:
        self.client = client
        self.model = model
        self.price = price
        self.fallbacks = fallbacks and model in FALLBACK_MODELS

    async def check(self) -> None:
        try:
            await self.client.models.retrieve(self.model)
        except anthropic.AuthenticationError as err:
            raise AIError("invalid_auth", retryable=False) from err
        except anthropic.NotFoundError as err:
            raise AIError("unknown_model", retryable=False) from err
        except anthropic.APIConnectionError as err:
            raise AIError("cannot_connect") from err
        except anthropic.APIStatusError as err:
            raise AIError(f"api_error:{err.status_code}") from err

    def _params(self, request: AIRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": request.messages,
        }
        output_config: dict[str, Any] = {}
        if request.effort:
            output_config["effort"] = request.effort
        if request.schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.schema}
        if output_config:
            params["output_config"] = output_config
        if request.tools:
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in request.tools
            ]
        if self.fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def complete(self, request: AIRequest) -> AIResponse:
        try:
            message = await self.client.with_options(timeout=request.timeout).beta.messages.create(
                **self._params(request)
            )
        except anthropic.AuthenticationError as err:
            raise AIError("invalid_auth", retryable=False) from err
        except anthropic.PermissionDeniedError as err:
            raise AIError("permission_denied", retryable=False) from err
        except anthropic.BadRequestError as err:
            raise AIError(f"bad_request:{err.message}"[:300], retryable=False) from err
        except anthropic.RateLimitError as err:
            raise AIError("rate_limited") from err
        except anthropic.APITimeoutError as err:
            raise AIError("timeout") from err
        except anthropic.APIConnectionError as err:
            raise AIError("cannot_connect") from err
        except anthropic.APIStatusError as err:
            raise AIError(f"api_error:{err.status_code}", retryable=err.status_code >= 500) from err
        return self._response(message, request)

    def _response(self, message: Any, request: AIRequest) -> AIResponse:
        usage = message.usage
        out = AIResponse(
            stop_reason=str(message.stop_reason or ""),
            model=str(message.model or self.model),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            provider=self.name,
        )
        out.cost = self.price.cost(out.input_tokens, out.output_tokens, out.cache_read_tokens, out.cache_write_tokens)
        if out.stop_reason == "refusal":
            raise AIError("refusal", retryable=True, refusal=True)
        texts: list[str] = []
        for block in message.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                out.tool_calls.append(ToolCall(block.id, block.name, dict(block.input or {})))
        out.text = "".join(texts).strip()
        # replay every block unchanged when the tool loop continues (thinking blocks included)
        out.assistant_message = {"role": "assistant", "content": [b.to_dict() for b in message.content]}
        if request.schema is not None and out.text and not out.tool_calls:
            try:
                out.data = json.loads(out.text)
            except ValueError as err:
                raise AIError("bad_json") from err
        if out.stop_reason == "max_tokens" and request.schema is not None and out.data is None:
            raise AIError("max_tokens")
        return out

    def tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> list[dict[str, Any]]:
        # all results of one turn go back in a single user message
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}
                    for call, content, is_error in results
                ],
            }
        ]
