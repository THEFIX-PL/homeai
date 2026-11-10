# Privacy

Everything HomeAI stores stays in Home Assistant. Data leaves the house only when you add a cloud AI tier, and
then only what the privacy level allows. The level is a setting for the whole home and can be set per tier
(a local model can get *full*).

| Level | What a cloud model receives |
|---|---|
| Minimal | People as “Person A”, rooms as “Room A”, devices as “Device A”; no situation titles or descriptions, no journal, no calendar titles; answers are translated back to real names locally |
| Standard (default) | Names of devices, rooms and people; never entities or areas you exclude, never entities labelled *HomeAI: private*, never secrets |
| Full | Standard plus calendar titles |

Never sent at any level: API keys, tokens, passwords, camera stream addresses and similar attributes. With *Log
prompts* the AI tab shows the last request to each tier. Diagnostics redact keys, tokens and user ids.

The AI-written digest and weekly review are skipped with the minimal level, because they carry real names.
