# HomeAI

Home intelligence for [Home Assistant](https://www.home-assistant.io/). HomeAI notices what changes in your
home, decides how serious it is and who is needed, fixes what it can on its own, and tells people only when a
person is needed. AI is optional: HomeAI works in plain code and uses AI tiers for judgement, conversation and
learning when you add them.

## What it does

- **Notices.** Generic detectors for safety (leak, smoke, gas, carbon monoxide), security (doors, windows,
  gates and locks while nobody is home or everyone sleeps), unresponsive devices, failing integrations,
  backups, updates, log errors, the internet connection, batteries, consumables, plants and their watering, silent sensors,
  indoor climate, disagreeing sensors, lights in an empty home, windows open while heating, hubs and bridges
  (Zigbee2MQTT and any hub other devices connect through), unusual values against learned norms, and
  signals from other integrations, plus your own rules (custom detectors) written in the panel.
- **Understands.** Signals become *situations*: related signals are grouped (a hub offline explains every
  device behind it, the internet down explains cloud devices), flickers are ignored, and each situation has a
  lifecycle (pending, open, clearing, resolved).
- **Decides who is needed.** Every situation gets a severity (0 information to 4 critical), an urgency and
  who is needed: nobody, a household member, an administrator or a technician. Critical labels, presence and
  people's past reactions adjust it; safety is never lowered.
- **Fixes first.** Repair playbooks (reload an integration, wait for it to retry, retry a backup, restart an
  add-on, suggested actions) run before anyone is bothered. Protective actions (close the water valve on a
  leak) run at once on entities you label, while people are told.
- **Tells the right people.** Escalation ladders per severity, presence- and sleep-aware recipients, phone
  actions (*Got it*, *I'll handle it*, *Snooze*), daily limits, digest, speech and an event channel for
  custom displays.
- **Acts safely.** One risk policy (R0 read … R6 destructive) for people, autonomy, the plan, repairs and AI.
  Autonomous actions run as the dedicated `HomeAI` user, are verified, logged in the logbook and can be undone.
- **Plans.** The home's plan (actions and reminders, once, daily, on weekdays, around sunrise and sunset) and
  presence exceptions (trips, guests, working from home) as calendars any automation can read.
- **Thinks, when you let it.** Three optional AI tiers: P1, a cheap or local everyday brain; P2, an
  investigator with tools; P3, an arbiter for the hardest decisions. Budgets, privacy levels and a hard rule
  that AI never acts outside the policy.
- **Learns.** Norms for each hour of the week, habits proposed for the plan (saved only after approval),
  memory of facts and preferences, feedback from undo and refusals, and a weekly review.
- **Configurable from the UI.** Every threshold, delay, limit, channel and model is a field in the HomeAI panel
  — 270+ settings, many of them per floor, area, device, entity or person. See [docs/settings.md](docs/settings.md).

## Requirements

- Home Assistant **2026.11** or newer.
- Optional: an Anthropic API key and/or an OpenAI-compatible server (Ollama, llama.cpp, vLLM, LM Studio…) for
  the AI tiers.

## Installation

1. In Home Assistant open the **Marketplace**, add `https://github.com/THEFIX-PL/homeai` as a custom repository
   (category **Integration**) and install **HomeAI**. Manual installation: copy `custom_components/homeai`
   into `config/custom_components` and restart.
2. **Settings → Devices & services → Add integration → HomeAI.** The wizard asks for the language, how much
   data may go to cloud AI, and each person's role (administrator, member, guest, ignore).
3. Open the **HomeAI** panel in the sidebar. Situations, approvals, a chat, the plan, presence exceptions,
   learning, your own rules, the journal, all settings (for the whole home or per floor, room, device, entity
   or person, with history, import and export) and the AI status are there.
4. Optional: on the integration's page choose **Add AI tier** to add P1, P2 or P3. The connection is checked
   without spending tokens.

For the first two weeks (setting *Observation period*) HomeAI only observes the comfort and device actions it
would take on its own: the journal shows what it would have done.

## Entities, services and events

| What | Purpose |
|---|---|
| `sensor.homeai_situations` | Number of open situations that need attention; attribute `situations` with the list |
| `binary_sensor.homeai_attention_needed` | On while something of severity 2+ is not acknowledged |
| `event.homeai_situation`, `event.homeai_notification` | Lifecycle and notification events for automations and displays |
| `calendar.homeai_plan`, `calendar.homeai_presence` | The plan and presence exceptions |
| `select.homeai_autonomy` | One slider over the whole policy: only observe, cautious, balanced, bold (administrators only) |
| `switch.homeai_ai`, `switch.homeai_vacation`, `number.homeai_ai_budget_monthly` | AI on or off, vacation mode, monthly AI budget |
| `sensor.homeai_next_plan_change` | When the plan does something next, and what |
| `switch.homeai_notifications_paused` | Pause notifications (critical ones still go out by default) |
| `sensor.homeai_ai_cost_today`, `sensor.homeai_ai_cost_month` | Estimated AI spend |
| `conversation.homeai` | Talk to HomeAI from Assist and voice satellites |
| Services `homeai.*` | `ask` (returns HomeAI's answer), `watch` (“tell me when”), `run_mission`, `report_signal`, `clear_signal`, `acknowledge`, `handle`, `snooze`, `dismiss`, `send_digest`, `approve`, `deny`, `undo`, `plan_add`, `plan_remove`, `plan_skip`, `presence_add`, `presence_remove` |
| LLM API “HomeAI” | Other assistants can read situations and act through HomeAI's policy |

Dashboard cards, with no resource to add: `custom:homeai-situations-card` (open situations with quick
reactions), `custom:homeai-plan-card` (what the plan does next) and `custom:homeai-chat-card` (talk to HomeAI
in your own account).

## Documentation

- [Architecture](docs/architecture.md): how signals become situations, decisions and actions.
- [Risk policy](docs/policy.md): classes, autonomy levels, approvals, protective actions.
- [AI tiers](docs/ai.md): providers, budgets, escalation, the arbiter, evals.
- [Privacy](docs/privacy.md): what leaves the house at each level.
- [Integrating with HomeAI](docs/integrations.md): signals from other integrations, events, calendars,
  blueprints.
- [All settings](docs/settings.md): generated from the settings registry.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md). License:
[Apache-2.0](LICENSE).
