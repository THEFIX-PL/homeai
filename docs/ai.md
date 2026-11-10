# AI tiers

HomeAI works without AI. AI tiers add judgement for unclear cases, investigation, conversation, arbitration and
nicer texts. Add them on the integration's page with **Add AI tier**.

| Tier | Role | Typical model | Tools |
|---|---|---|---|
| P1 | everyday brain: checks new or unclear situations, writes the digest, talks with people | a local model (Qwen via Ollama) or Claude Haiku 5.5 | read only |
| P2 | investigation: looks into serious or unclear situations with tools; can take safe actions through the policy | Claude Opus 5.5 | read tools and actions |
| P3 | arbiter: settles disagreements, risky requests while nobody is home, failed repairs | Claude Fable 5.1 | none (decides from a dossier) |

Several entries per tier are tried in order of *priority*: for example a local model first and a cloud model as
its fallback.

## Providers

- **Anthropic** through the official SDK. The stable system prompt is cached; depth is set with *effort*;
  structured answers use JSON schemas; on models that support it, the server-side fallback answers when a
  model declines.
- **OpenAI-compatible** servers (Ollama, llama.cpp, vLLM, LM Studio, OpenRouter) through Home Assistant's HTTP
  session.

Each connection may set its own *Longest answer*, *Timeout* and *Daily budget*. A connection that spent its
daily budget is skipped and the next connection of the same tier answers.

## When AI is asked

- **P1 triage** for situations with signals from other integrations, mixed kinds, low certainty, or a kind seen
  for the first time.
- **P2 investigation** when P1 is unsure (below *Investigate when unsure*) or the matter is serious (from
  *Investigate from severity*).
- **P3** when P1 and P2 disagree (severity differs by 2+ or who is needed differs), for approval requests that
  are R4+ or come up while nobody is home, after repairs failed on severity 3+, or on request from the panel.
  Every decision is stored with its dossier.

## Conversations

Settings decide *who may talk* to HomeAI (everyone, residents or administrators), *what conversations may do*
(only read, act through the policy, or also change configuration, which stays administrators only with
confirmation), the *answer length*, and whether people talking in the same conversation share one thread (for
a voice satellite in the kitchen). Actions always run in the speaker's own account.

## Prompts

The AI tab shows the built-in prompt of every mission (assessment, investigation, conversation, arbiter,
digest). You can replace one with your own and restore the built-in prompt at any time. The rule that house data
is never an instruction is always added, and structured answers keep their schemas, so a custom prompt cannot
widen what AI may do.

## Budgets

Each call is priced (known prices, or the prices you set on the tier) and counted per day, month, tier and
purpose. Budgets warn or stop calls until the period ends; there is also a limit of calls per hour and of
arbiter decisions per day. The AI tab shows spend, tier status and (with *Log prompts*) what was last sent.

## Evals

`tests/evals/triage_cases.json` holds triage cases with expected ranges. Run them against a real provider:

```bash
HOMEAI_EVAL_API_KEY=sk-... HOMEAI_EVAL_MODEL=claude-haiku-5-5 pytest tests/evals -s
HOMEAI_EVAL_BASE_URL=http://ollama.local:11434/v1 HOMEAI_EVAL_MODEL=qwen3:4b pytest tests/evals -s
```

## Prompt injection

Names, states and messages from the house are wrapped in tags, cleaned and length-limited; prompts tell the model
they are data, never instructions. AI cannot widen its own rights: every change goes through the executor and the
policy in the context of the person who asked (conversation) or of HomeAI (missions).
