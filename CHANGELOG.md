# Changelog

All notable changes to HomeAI are documented here. The project follows
[Semantic Versioning](https://semver.org/).

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
