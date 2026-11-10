# Changelog

All notable changes to HomeAI are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [1.1.0]

### Added
- Interfaces from the plan: the autonomy slider `select.homeai_autonomy`, `switch.homeai_ai`,
  `switch.homeai_vacation`, `number.homeai_ai_budget_monthly`, `sensor.homeai_next_plan_change`,
  `binary_sensor.homeai_attention_needed`, the services `homeai.ask` and `homeai.run_mission`, and Repairs hints
  for a home without residents, phones or areas.
- Custom detectors without code: rules in the panel's Rules tab (entities, label, area or domain; state, above,
  below, unavailable; how long; when; each or all) with a live preview.
- Panel: chat, presence exceptions, a form for the plan, settings per floor, room, device, entity or person,
  settings history, section reset and import; dashboard cards for the plan and for chat.
- Policy: an actor × class matrix (HomeAI's own rules, AI, repairs, the plan), risk classes by action and by
  label, choice of repair playbooks and integrations never reloaded, who may add to the plan and defaults for
  new entries.
- AI: prompts per mission with the built-in prompt shown and restorable; who may talk to HomeAI, what
  conversations may do, answer length and shared conversations; longest answer, timeout and daily budget per
  tier connection.
- “Tell me when” commitments (`homeai.watch`, also from conversations), plans from other integrations through a
  `homeai_plan` attribute, a plant watering detector for soil moisture sensors, notification title and text
  templates, and a performance test for a large home.

## [1.0.0]

First release of HomeAI 1.0, rewritten from scratch.

### Added
- Setup wizard (language, privacy, roles of people), quick options and a settings registry with 230+ settings,
  many per floor, area, device, entity or person, with history, undo, export and import.
- World model from Home Assistant's registries, roles for entities, presence and sleep from four sources.
- Detectors for safety, security, availability, integrations, backups, updates, the log, the internet,
  batteries, consumables, problems and plants, silent sensors, indoor environment, disagreeing sensors, lights
  in an empty home, windows open while heating, hubs and bridges, anomalies against learned norms, and signals
  from other integrations (service or entity attribute).
- Situation engine with correlation, suppression and a lifecycle; triage with severity, urgency and who is
  needed; people's reactions (acknowledge, take, snooze, dismiss).
- Notification router with escalation ladders, presence- and sleep-aware recipients, phone actions, digest,
  speech and an event channel; blueprints for AWTRIX and notify displays.
- Risk policy R0–R6 with autonomy levels, an observation period and protective actions; the `HomeAI` system
  user; executor with verification, undo, journal and logbook; approvals; configuration editing through Home
  Assistant's own editors.
- Repair playbooks with retries and escalation; adapter for hubs, bridges and Zigbee2MQTT.
- The home's plan and presence exceptions as calendars.
- AI tiers P1, P2 and P3 as subentries: Anthropic and OpenAI-compatible providers, budgets, privacy levels,
  P1 triage, P2 investigation with tools, conversations, the HomeAI LLM API, the arbiter with decision
  dossiers, AI-written digest and weekly review, and a triage eval.
- Learning: norms, anomalies, habit proposals, memory of facts and preferences, feedback from undo and
  refusals, weekly review.
- Panel (situations, approvals, plan, learning, journal, settings, AI) and a dashboard card.
