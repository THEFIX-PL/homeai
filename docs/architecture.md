# Architecture

HomeAI is one Home Assistant integration. A config entry runs one runtime with these stages, in data-flow order:

```
world model ─▶ detectors ─▶ signals ─▶ situation engine ─▶ repair ─▶ triage ─▶ notifications
                                │                 │            │          ▲
                                │                 ▼            ▼          │
                                │              policy ◀─── executor ◀── AI tiers (P1, P2, P3)
                                ▼                 ▲            │
                           adapters            approvals   journal, logbook
```

## World model

Built from Home Assistant's registries (floors, areas, devices, entities, labels, people) and states, updated
incrementally on registry and state events. Each entity gets *roles* from its domain, device class and
translation key (light, outlet, leak, smoke, battery, temperature, connectivity…). HomeAI ignores its own
device and entities, entities with the *HomeAI: ignore* label, disabled entities and (by default) hidden
ones. The scope can be limited to selected areas or to entities exposed to assistants.

Presence comes from `person` entities; roles (administrator, member, guest, ignore) are settings per person.
Sleep comes from up to four sources in order: a helper per person, bed or charging sensors, an AI guess, and
night hours (with weekend hours for Friday and Saturday nights).

## Detectors and signals

A detector looks at the world and returns *signals*: id, kind, category (safety, security, damage, system,
energy, comfort, maintenance, info), severity, entities, data for texts, who is needed, a correlation `root`,
`tags` and `suppresses` tags, an optional repair playbook and an optional suggested action. Detectors are
re-evaluated one second after a watched entity changes and on every tick (default one minute). Every
threshold is a setting, most of them per entity, device, area or floor.

Custom detectors are rules you write in the panel's **Rules** tab: entities (listed, or by label, area or
domain), a condition (state is or is not a value, above or below a number, unavailable), how many minutes it
must hold, when the rule applies (always, at night, while everyone is away or while someone is home) and
whether each entity opens its own signal or only all of them together. Each rule sets the severity, category,
who is needed and the advice shown to people. The rule editor previews which entities it covers and which of
them meet the condition right now.

## Situations

Signals with the same root form one situation. A signal that suppresses tags (internet down → `cloud`, a hub
offline → `via:<hub>`) pulls the signals it explains into its own situation. A new situation waits a minimum
time per category (no wait for safety) and nothing opens during the startup grace period. When its signals
are gone it waits before resolving and reopens if they come back. People can acknowledge, take, snooze or
dismiss (“not a problem”, which mutes the signals for some days and teaches calibration).

Processors run on every lifecycle event in order: repair, triage, notifications; then entities, the bus event
`homeai_situation` and listeners (AI, arbiter).

## Triage

Code decides first: overrides per kind, the *HomeAI: critical* label (severity 4), raised severity for
safety, security and damage when everyone is away, lowered severity for kinds that are often dismissed (never
safety). While a repair playbook is trying, nobody is needed unless the situation is critical. AI tiers can
refine the assessment later; guards keep safety severity, require a person for critical matters, and accept
“nobody needed” only below high severity.

## Repair

When a situation opens, its playbook (or suggested action) is planned with a wait, tried through the executor
as `repair`, verified for a while and retried with backoff. Failure or refusal escalates the situation so
people are told that HomeAI tried. Protective actions for safety alarms run at once on labelled entities.

## Notifications

A ladder per severity: after N minutes, to whom (everyone, people at home, at home or everyone, administrators,
people awake at home), through which channels (push, persistent notification, speech, event), whether to
repeat and whether it may wake people. Phones are discovered from the Companion app; any notify entity or
service can be added per person. Acknowledging, taking, snoozing, dismissing or resolving clears what was
sent. A digest summarises open matters at set times.

## Policy and executor

See [policy.md](policy.md). The executor validates, asks the policy, picks the context (the person or the
`HomeAI` system user), snapshots states for undo (comfort and device actions, through `scene.create`), calls the
service with a timeout, waits for the expected state, writes the journal, the logbook and the `homeai_action`
event. Configuration changes go through Home Assistant's own editor APIs (REST config views and WebSocket
commands) authenticated as the `HomeAI` user, with the previous configuration kept for undo.

## Plan and presence

The scheduler stores entries with their author and the risk class approved when they were created, and runs
them through the executor as `schedule`. Missed entries run if they are only slightly late. Presence exceptions
make the household or a person expected away; they feed presence (vacation) and the presence calendar.

## AI

See [ai.md](ai.md). AI tiers never act directly: they return assessments and texts, and their tools change
things only through the executor and the policy.

## Learning

Norms per entity and hour of the week from the recorder's long-term statistics feed an anomaly detector.
Habits from repeated manual actions become proposals. Undo and refusals adjust what HomeAI does on its own.
A weekly review summarises the week for administrators.

## Storage

Everything lives in Home Assistant's `.storage` (settings, journal, situations, approvals, plan, presence
exceptions, AI ledger, dossiers, memory, learning). Diagnostics export the state with secrets redacted.
