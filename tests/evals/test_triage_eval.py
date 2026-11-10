"""Triage eval against a real provider. Costs money, so it runs only when asked:

    HOMEAI_EVAL_API_KEY=sk-... HOMEAI_EVAL_MODEL=claude-haiku-5-5 pytest tests/evals -s

For an OpenAI-compatible server (e.g. Ollama) set HOMEAI_EVAL_BASE_URL and HOMEAI_EVAL_MODEL instead.
Each case passes when severity is within the expected range and `who` is one of the allowed values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from homeassistant.core import HomeAssistant
import pytest

from custom_components.homeai.signals.base import Category, Need, Signal

from ..common import setup_homeai
from ..home import standard_home

CASES = json.loads((Path(__file__).parent / "triage_cases.json").read_text())
KEY = os.environ.get("HOMEAI_EVAL_API_KEY", "")
BASE_URL = os.environ.get("HOMEAI_EVAL_BASE_URL", "")
pytestmark = pytest.mark.skipif(not (KEY or BASE_URL), reason="set HOMEAI_EVAL_API_KEY or HOMEAI_EVAL_BASE_URL")


@pytest.fixture
def allow_network(socket_enabled):  # pytest-socket is on in HA tests
    return None


async def test_triage_eval(hass: HomeAssistant, allow_network) -> None:
    tier = {
        "tier": "p1",
        "provider": "openai_compatible" if BASE_URL else "anthropic",
        "model": os.environ.get("HOMEAI_EVAL_MODEL", "claude-haiku-5-5"),
        "api_key": KEY,
        "base_url": BASE_URL,
    }
    standard_home(hass)
    rt = await setup_homeai(hass, {"ai.triage_enabled": False, "ai.budget_mode": "warn"}, subentries=[tier])
    ai, engine = rt.module("ai"), rt.module("situations")
    passed, rows = 0, []
    for case in CASES:
        signals = {}
        for i, raw in enumerate(case["signals"]):
            sid = f"eval:{case['name']}:{i}"
            signals[sid] = Signal(
                id=sid,
                detector="eval",
                kind=raw["kind"],
                category=Category(raw["category"]),
                severity=raw["severity"],
                data=raw.get("data", {}),
                need=Need(raw.get("need", "member")),
                confidence=raw.get("confidence", 1.0),
                root=f"eval:{case['name']}",
            )
        engine.on_signals(signals)
        await hass.async_block_till_done()
        await engine.process()
        s = next(x for x in engine.open() if x.group == f"eval:{case['name']}")
        result = await ai.triage(s)
        lo, hi = case["expect"]["severity"]
        ok = result is not None and lo <= result["severity"] <= hi and result["who"] in case["expect"]["who"]
        passed += ok
        rows.append(
            (case["name"], ok, result and result["severity"], result and result["who"], result and result["confidence"])
        )
        engine.on_signals(dict.fromkeys(signals))
        await hass.async_block_till_done()
    for row in rows:
        print("PASS" if row[1] else "FAIL", *row[0:1], *row[2:])
    print(f"{passed}/{len(CASES)} passed, cost ${ai.ledger.today():.4f}")
    assert passed >= len(CASES) * 0.75
