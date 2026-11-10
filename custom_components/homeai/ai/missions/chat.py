"""Conversations with people: separate threads per conversation, in the person's own Home Assistant account."""

from __future__ import annotations

from typing import Any

from homeassistant.util import dt as dt_util

from ..agent import run_agent
from ..context import home_card, moment_card
from ..privacy import Privacy, clean
from ..prompts import CHAT
from ..tools import ToolContext

MAX_THREADS = 50


def _prune(messages: list[dict[str, Any]], turns: int) -> list[dict[str, Any]]:
    """Keep the last `turns` turns; a turn starts with a user message that carries text (not tool results)."""
    starts = [i for i, m in enumerate(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)]
    if len(starts) <= turns:
        return messages
    return messages[starts[-turns] :]


async def chat(ai: Any, text: str, conversation_id: str, user_id: str | None) -> tuple[str, list[dict[str, Any]]]:
    rt = ai.rt
    tier = str(rt.settings.get("ai.chat_tier"))
    if not ai.available(tier):
        tier = "p2" if tier == "p1" else "p1"
    cfg = ai.first(tier)
    if cfg is None:
        return rt.text("ai|no_tier"), []
    privacy = Privacy(rt, ai.privacy_level(cfg))
    thread = ai.threads.get(conversation_id)
    if thread is None or thread["user_id"] != user_id or thread["tier"] != tier:
        thread = {"user_id": user_id, "tier": tier, "source": "", "messages": []}
    ai.threads[conversation_id] = thread
    while len(ai.threads) > MAX_THREADS:
        ai.threads.pop(next(iter(ai.threads)))
    person = next((p.name for p in rt.world.persons.values() if user_id and p.user_id == user_id), None)
    speaker = privacy.person(person) if person else "unknown"
    facts = ""
    memory = rt.module("memory")
    if memory is not None and privacy.level != "minimal":
        person_id = next((p.entity_id for p in rt.world.persons.values() if user_id and p.user_id == user_id), None)
        found = memory.search(text, scopes=["home", *([f"person:{person_id}"] if person_id else [])], limit=5)
        if found:
            facts = "<facts>\n" + "\n".join(f"- {clean(f['text'], 200)}" for f in found) + "\n</facts>\n"
    content = f"{moment_card(rt, privacy, journal=4)}\n{facts}\n<speaker>{speaker}</speaker>\n{text}"
    messages = [*thread["messages"], {"role": "user", "content": content}]
    system = CHAT.replace("{name}", str(rt.settings.get("general.assistant_name"))) + "\n" + home_card(rt, privacy)
    ctx = ToolContext(rt, privacy, actor="person", user_id=user_id)
    result = await run_agent(
        ai,
        tier,
        system=system,
        messages=messages,
        ctx=ctx,
        toolset="chat",
        max_steps=int(rt.settings.get("ai.chat_max_steps")),
        max_tokens=4096,
        purpose="chat",
        source=thread["source"] or None,
    )
    if result is None:
        return rt.text("ai|unavailable"), []
    thread["source"] = result.source
    thread["messages"] = _prune(result.messages, int(rt.settings.get("ai.chat_turns")))
    thread["updated"] = dt_util.utcnow().isoformat(timespec="seconds")
    reply = privacy.restore(result.text) if result.text else rt.text("ai|unavailable")
    return reply, result.actions
