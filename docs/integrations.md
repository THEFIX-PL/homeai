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
  It also shows what other integrations plan (below).
- `calendar.homeai_presence`: trips, guests, working from home, sickness. Create events from any calendar UI;
  the title picks the kind (“Vacation Anna”, “Goście”). Heating or other integrations can read it with a
  calendar trigger.

## Publish your plans

**Entity attribute** `homeai_plan`: any entity may expose a list of `{start, title, end?}` (ISO times; up to 50).
HomeAI shows these in `calendar.homeai_plan` and in the panel's plan next to its own entries, so people see
everything the house will do in one place. HomeAI never runs them; your integration does. Setting *Plans from
other integrations* turns this off.

```yaml
homeai_plan:
  - start: "2026-11-12T22:00:00+01:00"
    end: "2026-11-13T00:30:00+01:00"
    title: "Dishwasher: eco program"
```

## “Tell me when”

**Service** `homeai.watch`: `entity_id`, `condition` (state, not_state, above, below, changes), `value`,
`message`, `hours`. HomeAI tells the calling person once when the entity meets the condition, then stops. People
can ask the same in a conversation (“tell me when the washing machine is done”); the panel's plan lists what is
being watched.

## Blueprints

`blueprints/automation/homeai/` contains:

- **notification_to_awtrix.yaml**: show HomeAI notifications on an AWTRIX clock over MQTT.
- **notification_to_notify.yaml**: send HomeAI notifications to any notify entity (a TV, a tablet, a display).

## LLM API

Select the **HomeAI** API in any conversation agent to let it read situations, the plan and states, and act through
HomeAI's policy in the speaking person's account.
