# Integrating with HomeAI

Other integrations and automations can talk to HomeAI through stable contracts.

## Report signals

**Service** `homeai.report_signal`: `id`, `title`, optional `description`, `severity` 0–4, `category` (safety,
security, damage, system, energy, comfort, maintenance, info), `need` (nobody, member, admin, service),
`entities`, `group` (signals with the same group form one situation), `expires_minutes`. `homeai.clear_signal`
with the same `id` clears it.

**Entity attribute** `homeai_signals`: any entity may expose a list of
`{id, title, severity, category?, description?, need?, group?}`; HomeAI reads it on every evaluation and
removes signals that disappear from the list.

## Events

| Event | When | Data |
|---|---|---|
| `homeai_situation` | situation lifecycle | `event` (opened, updated, escalated, acknowledged, snoozed, handled, dismissed, resolved), `id`, `kind`, `category`, `severity`, `title`, `who`, `entities` |
| `homeai_notification` | a ladder step with the `event` channel, and when it is cleared | `situation_id`, `title`, `message`, `severity`, `category`, `kind`, `state` (active, cleared), `critical` |
| `homeai_action` | every action HomeAI ran, refused or observed | `action_id`, `status`, `risk`, `what`, `actor`, `situation_id`, `entities` |
| `homeai_approval` | approval requests and decisions | `id`, `status`, `what`, `risk` |

The same lifecycle is available as `event.homeai_situation` and `event.homeai_notification` entities.

## Calendars

- `calendar.homeai_plan`: the home's plan. Create an event to add a reminder; delete an occurrence to skip it.
- `calendar.homeai_presence`: trips, guests, working from home, sickness. Create events from any calendar UI;
  the title picks the kind (“Vacation Anna”, “Goście”). Heating or other integrations can read it with a
  calendar trigger.

## Blueprints

`blueprints/automation/homeai/` contains:

- **notification_to_awtrix.yaml**: show HomeAI notifications on an AWTRIX clock over MQTT.
- **notification_to_notify.yaml**: send HomeAI notifications to any notify entity (a TV, a tablet, a display).

## LLM API

Select the **HomeAI** API in any conversation agent to let it read situations, the plan and states, and act through
HomeAI's policy in the speaking person's account.
