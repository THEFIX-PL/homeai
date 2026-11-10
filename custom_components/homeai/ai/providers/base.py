"""What every provider takes and returns, independent of the vendor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class AIError(Exception):
    """A provider call failed. `retryable` means another provider (or a later try) may succeed."""

    def __init__(self, message: str, *, retryable: bool = True, refusal: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.refusal = refusal


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(slots=True)
class AIRequest:
    system: str  # stable instructions (cached); volatile context goes into messages
    messages: list[dict[str, Any]]  # vendor-neutral: {"role": "user"|"assistant", "content": str | list}
    tools: list[ToolSpec] = field(default_factory=list)
    schema: dict[str, Any] | None = None  # JSON schema for a structured answer
    max_tokens: int = 4096
    effort: str | None = None
    purpose: str = ""
    timeout: float = 60.0


@dataclass(slots=True)
class AIResponse:
    text: str = ""
    data: Any = None  # parsed structured answer
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0
    assistant_message: dict[str, Any] | None = None  # to append to `messages` when continuing a tool loop
    provider: str = ""


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, request: AIRequest) -> AIResponse: ...

    async def check(self) -> None:
        """Verify the connection and credentials without spending tokens; raises AIError."""

    def tool_results(self, results: list[tuple[ToolCall, str, bool]]) -> list[dict[str, Any]]:
        """Messages that return tool results (call, content, is_error) in this vendor's format."""
