"""Known prices (USD per million tokens) used to estimate cost. Each AI tier can override them in its settings.

Cache writes cost 1.25× input; cache reads use the listed price. Unknown models count as free until the
administrator enters prices (local models are free).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None

    def cost(self, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
        read_price = self.cache_read if self.cache_read is not None else self.input * 0.1
        return (
            input_tokens * self.input
            + output_tokens * self.output
            + cache_read * read_price
            + cache_write * self.input * 1.25
        ) / 1_000_000


PRICES: dict[str, Price] = {
    "claude-fable-5-2": Price(8.0, 40.0, 0.20),
    "claude-fable-5-1": Price(10.0, 50.0),
    "claude-fable-5": Price(10.0, 50.0),
    "claude-opus-5-5": Price(4.0, 20.0, 0.20),
    "claude-opus-5": Price(5.0, 25.0),
    "claude-opus-4-8": Price(5.0, 25.0),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.10),
    "claude-sonnet-5": Price(2.0, 10.0),
    "claude-haiku-5-5": Price(0.10, 0.50),
    "claude-haiku-4-5": Price(1.0, 5.0),
}

DEFAULT_MODELS = {"p1": "claude-haiku-5-5", "p2": "claude-opus-5-5", "p3": "claude-fable-5-1"}
DEFAULT_EFFORT = {"p1": "low", "p2": "medium", "p3": "high"}


def price_for(model: str, override_input: float | None = None, override_output: float | None = None) -> Price:
    base = PRICES.get(model, Price(0.0, 0.0))
    if override_input is None and override_output is None:
        return base
    return Price(
        override_input if override_input is not None else base.input,
        override_output if override_output is not None else base.output,
        base.cache_read,
    )
