# Settings

Every option HomeAI has, as shown in the HomeAI panel (Settings tab). Generated from the settings registry by
`scripts/gen_settings_doc.py`; do not edit by hand.

*Scope* says where a value can be set: for the whole home, or overridden for a floor, area, device, entity
or person (the most specific value wins). *Confirm* marks changes that ask for confirmation because they
lower protection or change something important.

## General

Language, parts of the day, journal and panel.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Language** — Language of HomeAI's notifications, journal and AI replies. Auto follows Home Assistant. | `general.language` | `auto` | Auto (`auto`), English (`en`), Polski (`pl`) | home |  |
| **Assistant name** — How HomeAI calls itself in messages and conversations. | `general.assistant_name` | `HomeAI` | up to 40 characters | home |  |
| **Startup grace period** — After Home Assistant starts, integrations need time to come up. HomeAI does not announce situations or act during this time. | `general.startup_grace` | 120 | 0–1800 s | home | advanced |
| **Evaluation interval** — How often time-based checks run (unavailability, deadlines, schedules). | `general.tick_seconds` | 60 | 10–600 s | home | advanced |
| **Night starts** — Start of the night part of the day. | `general.night_start` | `23:00` |  | home |  |
| **Morning starts** — Start of the morning part of the day. | `general.morning_start` | `06:00` |  | home |  |
| **Day starts** — Start of the day part of the day. | `general.day_start` | `10:00` |  | home |  |
| **Evening starts** — Start of the evening part of the day. | `general.evening_start` | `18:00` |  | home |  |
| **Journal retention** — How long entries stay in HomeAI's journal. | `general.journal_retention_days` | 30 | 1–365 d | home |  |
| **Show panel in sidebar** — Show the HomeAI panel in Home Assistant's sidebar. | `general.panel_sidebar` | true |  | home |  |
| **Panel for administrators only** — Hide the HomeAI panel from non-administrators. | `general.panel_admin_only` | false |  | home |  |

## Home model

Which entities HomeAI watches and the labels it understands.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Which entities HomeAI sees** — All entities, only those exposed to voice assistants, or only selected areas. | `world.scope` | `all` | All entities (`all`), Exposed to assistants (`exposed`), Selected areas (`selected`) | home |  |
| **Selected areas** — Areas HomeAI watches when the scope is “selected areas”. | `world.include_areas` | [] |  | home |  |
| **Only these domains** — Limit HomeAI to these entity domains. Empty means all. | `world.include_domains` | [] |  | home | advanced |
| **Excluded entities** — Entity patterns HomeAI ignores, for example light.*_display. | `world.exclude_entities` | [] |  | home | advanced |
| **Include hidden entities** — Also watch entities hidden in Home Assistant. | `world.include_hidden` | false |  | home | advanced |
| **Create HomeAI labels** — Create the labels HomeAI understands (ignore, personal, critical, protective action, private) if they do not exist. | `world.create_labels` | true |  | home |  |
| **Label: ignore** — Entities and devices with this label are invisible to HomeAI. | `world.label_ignore` | `homeai_ignore` |  | home | advanced |
| **Label: personal** — Personal devices (phones, laptops) may go offline; that is not a problem of the home. | `world.label_personal` | `homeai_personal` |  | home | advanced |
| **Label: critical** — Problems with these devices are always treated as the highest severity. | `world.label_critical` | `homeai_critical` |  | home | advanced |
| **Label: protective action** — Actions on these entities may run automatically to protect the home (for example closing a water valve during a leak). | `world.label_protective` | `homeai_protective_action` |  | home | advanced |
| **Label: private** — Data of these entities is never sent to cloud AI. | `world.label_private` | `homeai_private` |  | home | advanced |

## People and sleep

Roles, house mode and how HomeAI knows who sleeps.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Role** — Administrators approve risky actions and configuration changes; members receive notifications; guests and ignored people are not residents. | `presence.role` | `member` | Administrator (`admin`), Member (`member`), Guest (`guest`), Ignore (`ignore`) | home, person |  |
| **House mode helper** — Optional helper (for example input_select) describing the house mode, such as home, away or vacation. | `presence.home_mode_entity` | `` |  | home |  |
| **Vacation mode** — The household is away: security matters are raised and the plan skips entries that need someone at home. | `presence.vacation_mode` | false |  | home |  |
| **Vacation states** — States of the house mode helper that mean a longer absence. | `presence.vacation_states` | ["vacation", "away"] |  | home | advanced |
| **Sleep sources** — Where HomeAI learns that someone sleeps, in order of trust: helper, sensors, AI inference, night hours. | `presence.sleep_sources` | ["helper", "sensors", "ai", "hours"] | Helper (`helper`), Sensors (`sensors`), AI inference (`ai`), Night hours (`hours`) | home |  |
| **Sleep helper** — Switch or helper that says a person is asleep. | `presence.sleep_helper` | `` |  | home, person |  |
| **Sleep helper state** — State of the sleep helper that means asleep. | `presence.sleep_helper_state` | `on` |  | home, person | advanced |
| **Night starts (workdays)** — Usual bedtime on workdays. | `presence.night_start` | `23:00` |  | home, person |  |
| **Night ends (workdays)** — Usual wake-up time on workdays. | `presence.night_end` | `07:00` |  | home, person |  |
| **Night starts (weekends)** — Usual bedtime on Friday and Saturday. | `presence.weekend_night_start` | `00:00` |  | home, person |  |
| **Night ends (weekends)** — Usual wake-up time on weekends. | `presence.weekend_night_end` | `09:00` |  | home, person |  |
| **Phone charging sensors** — Charging sensors of the person's phone; charging at night suggests sleep. | `presence.charging_entities` | [] |  | home, person |  |
| **Bed sensors** — Bed occupancy sensors of the person. | `presence.bed_entities` | [] |  | home, person |  |
| **Settling time** — How long a change in presence must last before HomeAI reacts. | `presence.quiet_minutes` | 30 | 5–240 min | home | advanced |

## Privacy

What may be sent to cloud AI.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Data sent to cloud AI** — Standard sends names of devices, rooms and people. Minimal replaces people and rooms with neutral labels. Full also sends calendar titles. | `privacy.level` | `standard` | Standard (`standard`), Minimal (`minimal`), Full (`full`) | home | confirm (change) |
| **Never send these entities** — Entities whose data never leaves your home. | `privacy.never_send_entities` | [] |  | home |  |
| **Never send these areas** — Areas whose data never leaves your home. | `privacy.never_send_areas` | [] |  | home |  |
| **Keep AI requests** — Store requests and replies of AI calls for troubleshooting. | `privacy.log_prompts` | false |  | home | advanced |
| **Keep AI requests for** — How long stored AI requests are kept. | `privacy.log_retention_days` | 7 | 1–90 d | home | advanced |

## Detection

What HomeAI watches and its limits.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **System data refresh** — How often backups, the log and automation traces are read. | `detectors.system_refresh` | 300 | 60–3600 s | home | advanced |
| **Custom detectors** — Your own rules: when an entity (or entities with a label, in an area, of a domain) meets a condition for a while, open a situation. Edit them in the panel's Rules tab. | `detectors.custom` | see panel |  | home |  |
| **Safety sensors: watch** — Watch leak, smoke, gas, carbon monoxide and tamper sensors. | `detectors.safety.enabled` | true |  | home | confirm (disable) |
| **Security: watch** — Watch doors, windows, gates and locks left open while nobody is home or everyone sleeps. | `detectors.security.enabled` | true |  | home | confirm (disable) |
| **Internet connection: watch** — Watch the home's internet connection. | `detectors.internet.enabled` | true |  | home |  |
| **Unresponsive devices: watch** — Watch devices whose entities are all unavailable. | `detectors.availability.enabled` | true |  | home |  |
| **Integrations: watch** — Watch integrations that failed to start or need a new sign-in, and Repairs issues. | `detectors.integrations.enabled` | true |  | home |  |
| **Backups: watch** — Watch failed, old or incomplete automatic backups. | `detectors.backups.enabled` | true |  | home |  |
| **Updates: watch** — Watch available updates. | `detectors.updates.enabled` | true |  | home |  |
| **Log and automations: watch** — Watch errors in Home Assistant's log and automations that failed. | `detectors.log.enabled` | true |  | home |  |
| **Batteries: watch** — Watch low batteries. | `detectors.battery.enabled` | true |  | home |  |
| **Consumables: watch** — Watch filters, brushes and other parts that need replacing. | `detectors.consumables.enabled` | true |  | home |  |
| **Devices reporting problems: watch** — Watch problem sensors and plants that need attention. | `detectors.problems.enabled` | true |  | home |  |
| **Silent sensors: watch** — Watch sensors that stopped reporting. | `detectors.stale.enabled` | true |  | home |  |
| **Indoor environment: watch** — Watch temperature, humidity, CO₂ and PM2.5 limits. | `detectors.environment.enabled` | true |  | home |  |
| **Disagreeing sensors: watch** — Watch temperature sensors in one room that disagree. | `detectors.divergence.enabled` | true |  | home |  |
| **Lights in an empty home: watch** — Watch lights left on while everyone is away. | `detectors.lights_away.enabled` | true |  | home |  |
| **Window open while heating: watch** — Watch a window open in a room that is being heated. | `detectors.window_heating.enabled` | true |  | home |  |
| **Signals from other integrations: watch** — Watch signals reported by automations and integrations. | `detectors.external.enabled` | true |  | home |  |
| **Hubs and bridges: watch** — Watch hubs and bridges (Zigbee2MQTT, hubs other devices connect through) and fold the devices behind them into one situation. | `detectors.bridges.enabled` | true |  | home |  |
| **Custom detectors: watch** — Run your own rules. | `detectors.custom.enabled` | true |  | home |  |
| **Water leak: severity** — Severity 0–4 of water leak (0 journal only, 4 critical). | `detectors.safety.severity_leak` | 4 | 0–4 | area, device, entity, floor, home | advanced |
| **Smoke: severity** — Severity 0–4 of smoke (0 journal only, 4 critical). | `detectors.safety.severity_smoke` | 4 | 0–4 | area, device, entity, floor, home | advanced |
| **Gas: severity** — Severity 0–4 of gas (0 journal only, 4 critical). | `detectors.safety.severity_gas` | 4 | 0–4 | area, device, entity, floor, home | advanced |
| **Carbon monoxide: severity** — Severity 0–4 of carbon monoxide (0 journal only, 4 critical). | `detectors.safety.severity_carbon_monoxide` | 4 | 0–4 | area, device, entity, floor, home | advanced |
| **Safety alarm: severity** — Severity 0–4 of safety alarm (0 journal only, 4 critical). | `detectors.safety.severity_safety` | 3 | 0–4 | area, device, entity, floor, home | advanced |
| **Tampering: severity** — Severity 0–4 of tampering (0 journal only, 4 critical). | `detectors.safety.severity_tamper` | 2 | 0–4 | area, device, entity, floor, home | advanced |
| **Open while away: wait** — How long a door, window or lock must stay open while everyone is away. | `detectors.security.away_minutes` | 10 | 0–720 min | area, device, entity, floor, home |  |
| **Open at night: wait** — How long something must stay open while everyone at home sleeps. | `detectors.security.night_minutes` | 30 | 0–720 min | area, device, entity, floor, home |  |
| **Windows at night** — Also report doors and windows (not only locks and gates) open at night. | `detectors.security.openings_at_night` | true |  | area, device, entity, floor, home |  |
| **Internet sensor** — Binary sensor that is on while the internet works. Empty: the first Ping sensor. | `detectors.internet.entity` | `` |  | home |  |
| **Internet down: wait** — How long the connection must be down before it counts. | `detectors.internet.minutes` | 2 | 0–120 min | home |  |
| **Internet down: severity** — Severity 0–4 of internet down (0 journal only, 4 critical). | `detectors.internet.severity` | 3 | 0–4 | home | advanced |
| **Unresponsive after** — How long all entities of a device must be unavailable. | `detectors.availability.minutes` | 15 | 1–10080 min | area, device, entity, floor, home |  |
| **Unresponsive device: severity** — Severity 0–4 of unresponsive device (0 journal only, 4 critical). | `detectors.availability.severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **Integration problem: severity** — Severity 0–4 of integration problem (0 journal only, 4 critical). | `detectors.integrations.severity` | 1 | 0–4 | home | advanced |
| **Repairs issues** — Report open issues from Settings → Repairs. | `detectors.integrations.repairs` | true |  | home |  |
| **Repairs issues: severity** — Severity 0–4 of repairs issues (0 journal only, 4 critical). | `detectors.integrations.repairs_severity` | 0 | 0–4 | home | advanced |
| **Backup too old after** — Hours since the last successful automatic backup. | `detectors.backups.max_age_hours` | 30 | 1–720 h | home |  |
| **Backup problem: severity** — Severity 0–4 of backup problem (0 journal only, 4 critical). | `detectors.backups.severity` | 1 | 0–4 | home | advanced |
| **Updates: severity** — Severity 0–4 of updates (0 journal only, 4 critical). | `detectors.updates.severity` | 0 | 0–4 | home | advanced |
| **Log window** — How far back log errors and failed automations count. | `detectors.log.window_hours` | 24 | 1–168 h | home | advanced |
| **Minimum log errors** — Report the log only from this many errors. | `detectors.log.min_errors` | 1 | 1–1000 | home | advanced |
| **Log errors: severity** — Severity 0–4 of log errors (0 journal only, 4 critical). | `detectors.log.severity` | 0 | 0–4 | home | advanced |
| **Failed automations** — Report automations whose last run failed. | `detectors.log.automations` | true |  | home |  |
| **Failed automation: severity** — Severity 0–4 of failed automation (0 journal only, 4 critical). | `detectors.log.automation_severity` | 1 | 0–4 | home | advanced |
| **Battery threshold** — Report batteries at or below this level. | `detectors.battery.threshold` | 20 | 1–99 % | area, device, entity, floor, home |  |
| **Low battery: severity** — Severity 0–4 of low battery (0 journal only, 4 critical). | `detectors.battery.severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **Low battery in a safety device: severity** — Severity 0–4 of low battery in a safety device (0 journal only, 4 critical). | `detectors.battery.safety_severity` | 2 | 0–4 | area, device, entity, floor, home | advanced |
| **Group batteries** — All low batteries in one situation. | `detectors.battery.group` | true |  | home |  |
| **Consumable threshold** — Report consumables with this much life left or less. | `detectors.consumables.percent` | 10 | 0–100 % | area, device, entity, floor, home |  |
| **Sensors showing usage** — Consumable sensors that show how much is used (100 = worn out) instead of what is left. | `detectors.consumables.used_up_entities` | [] |  | home | advanced |
| **Consumable: severity** — Severity 0–4 of consumable (0 journal only, 4 critical). | `detectors.consumables.severity` | 0 | 0–4 | area, device, entity, floor, home | advanced |
| **Device problem: severity** — Severity 0–4 of device problem (0 journal only, 4 critical). | `detectors.problems.severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **Plant problem: severity** — Severity 0–4 of plant problem (0 journal only, 4 critical). | `detectors.problems.plant_severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **Silent after** — Hours without a report from a measuring sensor. 0 turns this off. | `detectors.stale.hours` | 6 | 0–720 h | area, device, entity, floor, home |  |
| **Silent sensor: severity** — Severity 0–4 of silent sensor (0 journal only, 4 critical). | `detectors.stale.severity` | 0 | 0–4 | area, device, entity, floor, home | advanced |
| **Beyond limit for** — How long a value must stay beyond its limit. | `detectors.environment.minutes` | 20 | 0–1440 min | area, device, entity, floor, home |  |
| **Allowed difference** — Maximum difference between temperature sensors in one room. | `detectors.divergence.degrees` | 2.5 | 0.5–20 ° | area, floor, home |  |
| **Disagreeing sensors: severity** — Severity 0–4 of disagreeing sensors (0 journal only, 4 critical). | `detectors.divergence.severity` | 0 | 0–4 | home | advanced |
| **Lights on for** — How long lights must be on while everyone is away. | `detectors.lights_away.minutes` | 10 | 0–720 min | area, device, entity, floor, home |  |
| **Lights in an empty home: severity** — Severity 0–4 of lights in an empty home (0 journal only, 4 critical). | `detectors.lights_away.severity` | 2 | 0–4 | home | advanced |
| **Window open for** — How long a window must be open while heating. | `detectors.window_heating.minutes` | 10 | 0–720 min | area, device, entity, floor, home |  |
| **Window open while heating: severity** — Severity 0–4 of window open while heating (0 journal only, 4 critical). | `detectors.window_heating.severity` | 2 | 0–4 | area, device, entity, floor, home | advanced |
| **Read homeai_signals attributes** — Accept signals that other integrations publish in a homeai_signals attribute. | `detectors.external.attributes` | true |  | home | advanced |
| **Low temperature: watch** — Report low temperature indoors. | `detectors.environment.temperature_min_enabled` | true |  | area, device, entity, floor, home |  |
| **Low temperature: limit** — The limit for low temperature. | `detectors.environment.temperature_min` | 10.0 | -20–30 °C | area, device, entity, floor, home |  |
| **Low temperature: severity** — Severity 0–4 of low temperature (0 journal only, 4 critical). | `detectors.environment.temperature_min_severity` | 3 | 0–4 | area, device, entity, floor, home | advanced |
| **High temperature: watch** — Report high temperature indoors. | `detectors.environment.temperature_max_enabled` | true |  | area, device, entity, floor, home |  |
| **High temperature: limit** — The limit for high temperature. | `detectors.environment.temperature_max` | 30.0 | 15–60 °C | area, device, entity, floor, home |  |
| **High temperature: severity** — Severity 0–4 of high temperature (0 journal only, 4 critical). | `detectors.environment.temperature_max_severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **High humidity: watch** — Report high humidity indoors. | `detectors.environment.humidity_max_enabled` | true |  | area, device, entity, floor, home |  |
| **High humidity: limit** — The limit for high humidity. | `detectors.environment.humidity_max` | 70.0 | 30–100 % | area, device, entity, floor, home |  |
| **High humidity: severity** — Severity 0–4 of high humidity (0 journal only, 4 critical). | `detectors.environment.humidity_max_severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **Low humidity: watch** — Report low humidity indoors. | `detectors.environment.humidity_min_enabled` | false |  | area, device, entity, floor, home |  |
| **Low humidity: limit** — The limit for low humidity. | `detectors.environment.humidity_min` | 25.0 | 0–60 % | area, device, entity, floor, home |  |
| **Low humidity: severity** — Severity 0–4 of low humidity (0 journal only, 4 critical). | `detectors.environment.humidity_min_severity` | 0 | 0–4 | area, device, entity, floor, home | advanced |
| **High CO₂: watch** — Report high co₂ indoors. | `detectors.environment.co2_max_enabled` | true |  | area, device, entity, floor, home |  |
| **High CO₂: limit** — The limit for high co₂. | `detectors.environment.co2_max` | 1500.0 | 400–10000 ppm | area, device, entity, floor, home |  |
| **High CO₂: severity** — Severity 0–4 of high co₂ (0 journal only, 4 critical). | `detectors.environment.co2_max_severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **High PM2.5: watch** — Report high pm2.5 indoors. | `detectors.environment.pm25_max_enabled` | true |  | area, device, entity, floor, home |  |
| **High PM2.5: limit** — The limit for high pm2.5. | `detectors.environment.pm25_max` | 50.0 | 1–1000 µg/m³ | area, device, entity, floor, home |  |
| **High PM2.5: severity** — Severity 0–4 of high pm2.5 (0 journal only, 4 critical). | `detectors.environment.pm25_max_severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |

## Situations

When situations open and close.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Wait before announcing** — How long a new situation must last before anyone hears about it. | `situations.min_duration` | 60 | 0–3600 s | home |  |
| **Wait before closing** — How long a situation must be gone before it is closed. | `situations.close_after` | 300 | 0–86400 s | home |  |
| **“Not a problem” lasts** — Days a dismissed situation stays quiet. | `situations.dismiss_days` | 7 | 1–365 d | home |  |
| **Wait before announcing: safety** — Delay for safety situations (leak, smoke). | `situations.min_duration_safety` | 0 | 0–3600 s | home | advanced |
| **Wait before announcing: security** — Delay for security situations. | `situations.min_duration_security` | 30 | 0–3600 s | home | advanced |
| **Wait before announcing: damage** — Delay for situations that risk damage. | `situations.min_duration_damage` | 60 | 0–3600 s | home | advanced |

## Assessment

How serious a situation is.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Severity overrides** — Fixed severity per kind of situation, for example {"updates": 1}. | `triage.severity_overrides` | see panel |  | home | advanced |
| **Raise when nobody is home** — Safety, security and damage situations are one step more serious while everyone is away. | `triage.raise_when_away` | true |  | home |  |
| **Learn from “not a problem”** — Lower the severity of kinds that are dismissed again and again (never safety). | `triage.calibration_enabled` | true |  | home |  |
| **Learning: minimum situations** — How many situations of a kind before learning applies. | `triage.calibration_min_events` | 5 | 2–100 | home | advanced |
| **Learning: dismissed share** — Share of dismissed situations that lowers severity. | `triage.calibration_dismiss_ratio` | 0.6 | 0.1–1.0 | home | advanced |

## Notifications

Who hears what, how and when.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Pause notifications** — Stop all notifications except critical ones (see below). | `notify.paused` | false |  | home | confirm (change) |
| **Critical despite pause** — Critical situations are announced even while notifications are paused. | `notify.paused_allows_critical` | true |  | home | confirm (disable) |
| **Extra notification targets** — Notify entities or services for this person, besides discovered phones. | `notify.targets` | [] |  | home, person |  |
| **Discover phones** — Use the companion app devices of the person. | `notify.discover_apps` | true |  | home, person |  |
| **Include tablets and computers** — Also send to tablets and computers with the companion app. | `notify.include_tablets` | false |  | home, person |  |
| **Notifications per day** — Most non-critical notifications one person gets in a day. | `notify.max_per_day` | 20 | 1–500 | home |  |
| **Critical alerts break silence** — Critical situations use critical alerts that sound even in silent mode. | `notify.critical_sound` | true |  | home |  |
| **Snooze for** — How long “Snooze” silences a situation. | `notify.snooze_minutes` | 240 | 5–10080 min | home |  |
| **Tell when resolved** — Send a short message when a notified situation resolves. | `notify.announce_resolved` | false |  | home |  |
| **Open in panel** — Path a notification opens. | `notify.open_path` | `homeai` | up to 100 characters | home | advanced |
| **Speech engine** — Text-to-speech entity for spoken notifications. | `notify.tts_entity` | `` |  | home |  |
| **Speakers** — Media players used for spoken notifications. | `notify.tts_players` | [] |  | home |  |
| **Daily summary** — Send a summary of open situations at set times. | `notify.digest_enabled` | true |  | home |  |
| **Summary times** — Times (HH:MM) of the summary. | `notify.digest_times` | ["08:00", "20:00"] | –6 | home |  |
| **Summary recipients** — Who receives the summary. | `notify.digest_to` | `home_or_all` | Nobody (`none`), Everyone (`all`), People at home (`home`), People at home, else everyone (`home_or_all`), Administrators (`admins`), People awake at home (`awake_home`) | home |  |
| **Summary items** — Most situations listed in a summary. | `notify.digest_max_items` | 10 | 1–50 | home |  |
| **Escalation: severity 4** — Steps for critical situations: after minutes, to whom, channels, repeat, critical. | `notify.ladder_4` | see panel |  | home | confirm (change) |
| **Escalation: severity 3** — Steps for urgent situations: after minutes, to whom, channels, repeat, critical. | `notify.ladder_3` | see panel |  | home | confirm (change) |
| **Escalation: severity 2** — Steps for attention situations: after minutes, to whom, channels, repeat, critical. | `notify.ladder_2` | see panel |  | home |  |
| **Escalation: severity 1** — Steps for notice situations: after minutes, to whom, channels, repeat, critical. | `notify.ladder_1` | see panel |  | home | advanced |
| **Escalation: severity 0** — Steps for journal situations: after minutes, to whom, channels, repeat, critical. | `notify.ladder_0` | see panel |  | home | advanced |

## Policy

What HomeAI may do on its own, what needs a yes, and what never happens.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Autonomy** — One setting over the whole policy: only observe, cautious (propose comfort and device actions, repairs still run), balanced (the levels below) or bold (act on comfort and devices). Never stays never; configuration is never automatic. | `policy.slider` | `balanced` | Only observe (`observe`), Cautious (`cautious`), Balanced (`balanced`), Bold (`bold`) | home | confirm (change) |
| **Comfort actions (R1)** — What HomeAI may do on its own with lights, scenes, media and messages. | `policy.autonomy_r1` | `act_tell` | Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | confirm (change) |
| **Device actions (R2)** — What HomeAI may do on its own with appliances, covers, heating and cooling. | `policy.autonomy_r2` | `propose` | Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | confirm (change) |
| **System repairs (R3)** — Reloading integrations, restarting add-ons and retrying backups, only from repair playbooks. | `policy.autonomy_r3` | `act` | Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | confirm (change) |
| **Configuration (R4)** — Automations, scripts, scenes, helpers and dashboards. Never done without an administrator's yes. | `policy.autonomy_r4` | `propose` | Never (`never`), Only observe (`observe`), Propose and ask (`propose`) | home | confirm (change) |
| **Residents' device requests** — When a resident asks for a device action (R2): do it, or ask them to confirm first. | `policy.person_r2` | `act` | Do it (`act`), Ask to confirm (`confirm`) | home |  |
| **Observation period** — Days after installation during which comfort and device autonomy only observes. | `policy.observation_days` | 14 | 0–90 d | home | confirm (lower) |
| **Protective actions** — Allow safe-direction actions on entities labelled “HomeAI: protective action” (e.g. close the water valve on a leak), even for security devices. | `policy.protective_actions` | true |  | home | confirm (disable) |
| **System repairs per day** — Most automatic system repairs (R3) per day; more need an administrator. | `policy.repairs_per_day` | 10 | 1–100 | home | advanced |
| **Approval expires after** — How long a request for approval waits for an answer. | `policy.approval_minutes` | 120 | 5–10080 min | home |  |
| **Risk class** — Override the risk class of actions on this entity, device, area or floor. | `policy.risk_override` | `auto` | Automatic (`auto`), R0 read (`R0`), R1 comfort (`R1`), R2 devices (`R2`), R3 system (`R3`), R4 configuration (`R4`), R5 security (`R5`), R6 destructive (`R6`) | area, device, entity, floor, home | advanced, confirm (change) |
| **Risk class by action** — Your own class for a whole domain or one action, e.g. {"switch": "R3", "script.turn_on": "R4"}. The most specific key wins. | `policy.risk_by_service` | see panel |  | home | advanced, confirm (change) |
| **Risk class by label** — A class for everything with a label, by label id, e.g. {"kids_room": "R4"}. With several labels the highest class wins; an entity, device, area or floor override still comes first. | `policy.risk_by_label` | see panel |  | home | advanced, confirm (change) |
| **HomeAI's own rules: comfort (R1)** — Level for HomeAI's own rules with comfort (R1) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_homeai_r1` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **HomeAI's own rules: devices (R2)** — Level for HomeAI's own rules with devices (R2) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_homeai_r2` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **HomeAI's own rules: system (R3)** — Level for HomeAI's own rules with system (R3) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_homeai_r3` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **HomeAI's own rules: configuration (R4)** — Level for HomeAI's own rules with configuration (R4) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_homeai_r4` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`) | home | advanced, confirm (change) |
| **AI: comfort (R1)** — Level for AI with comfort (R1) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_ai_r1` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **AI: devices (R2)** — Level for AI with devices (R2) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_ai_r2` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **AI: system (R3)** — Level for AI with system (R3) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_ai_r3` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **AI: configuration (R4)** — Level for AI with configuration (R4) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_ai_r4` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`) | home | advanced, confirm (change) |
| **Repairs: comfort (R1)** — Level for Repairs with comfort (R1) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_repair_r1` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **Repairs: devices (R2)** — Level for Repairs with devices (R2) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_repair_r2` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **Repairs: system (R3)** — Level for Repairs with system (R3) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_repair_r3` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **Repairs: configuration (R4)** — Level for Repairs with configuration (R4) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_repair_r4` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`) | home | advanced, confirm (change) |
| **The plan: comfort (R1)** — Level for The plan with comfort (R1) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_schedule_r1` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **The plan: devices (R2)** — Level for The plan with devices (R2) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_schedule_r2` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **The plan: system (R3)** — Level for The plan with system (R3) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_schedule_r3` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`), Act and tell (`act_tell`), Act (`act`) | home | advanced, confirm (change) |
| **The plan: configuration (R4)** — Level for The plan with configuration (R4) actions; “As the class” uses the class's level. The autonomy slider still applies. | `policy.actor_schedule_r4` | `inherit` | As the class (`inherit`), Never (`never`), Only observe (`observe`), Propose and ask (`propose`) | home | advanced, confirm (change) |

## Actions

How actions are run, checked and undone.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Action timeout** — How long one service call may take. | `executor.timeout` | 30 | 5–300 s | home | advanced |
| **Check result for** — How long to wait for the expected state after an action. | `executor.verify_seconds` | 10 | 0–120 s | home | advanced |
| **Undo** — Snapshot comfort and device states before acting so actions can be undone. | `executor.undo` | true |  | home |  |
| **Undo history** — How many recent actions can be undone. | `executor.undo_keep` | 20 | 1–100 | home | advanced |
| **Cloud devices offline** — While the internet is down, refuse actions on cloud devices instead of waiting for them to fail. | `executor.block_cloud_offline` | true |  | home | advanced |
| **Local address** — Address HomeAI uses to reach this Home Assistant for configuration changes. Empty: localhost on the HTTP port. | `executor.local_url` | `` | up to 200 characters | home | advanced |

## Self-repair

How HomeAI fixes things before bothering anyone.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Self-repair** — Try repair playbooks before telling people. | `repair.enabled` | true |  | home | confirm (disable) |
| **Suggested actions** — Run actions that detectors suggest (e.g. turn off lights in an empty home), within the policy. | `repair.quick_actions` | true |  | home |  |
| **Protective actions on safety alarms** — On a leak, gas, smoke or carbon monoxide alarm run protective actions right away (people are notified at the same time). | `repair.protective_enabled` | true |  | home | confirm (disable) |
| **Attempts** — How many times a playbook is tried before people are told. | `repair.max_attempts` | 2 | 1–5 | home |  |
| **Pause between attempts** — Minutes between attempts (multiplied by the attempt number). | `repair.backoff_minutes` | 10 | 1–240 min | home | advanced |
| **Wait for the effect** — After an attempt, how long to wait for the situation to clear. | `repair.verify_minutes` | 5 | 1–120 min | home | advanced |
| **Reload: wait first** — Minutes before reloading a failed integration. | `repair.reload_wait` | 2 | 0–120 min | home | advanced |
| **Retrying integration: wait** — Minutes to let an integration that retries on its own come up before reloading it. | `repair.retry_wait` | 10 | 0–240 min | home | advanced |
| **Devices of one integration down: wait** — Minutes before reloading an integration whose devices all went silent. | `repair.outage_wait` | 5 | 0–240 min | home | advanced |
| **Backup: wait before retrying** — Minutes before retrying a failed backup. | `repair.backup_wait` | 30 | 0–1440 min | home | advanced |
| **Suggested action: wait** — Minutes before running a suggested action. | `repair.action_wait` | 0 | 0–240 min | home | advanced |
| **Repair playbooks in use** — Which repairs HomeAI may try on its own before telling anyone. | `repair.playbooks` | see panel | Reload an integration (`reload_entry`), Wait for an integration to retry, then reload (`wait_then_reload`), Reload after the internet returns (`reload_after_outage`), Retry a failed backup (`retry_backup`), Restart an add-on (`restart_addon`), Suggested quick actions (`action`) | home | confirm (disable) |
| **Never reload** — Integrations HomeAI never reloads, by domain (zha, mqtt) or config entry id. Their failures go straight to people. | `repair.never_reload` | [] | –100 | home |  |

## Hubs and bridges

Knowledge about hubs, bridges and Zigbee2MQTT.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Find hubs automatically** — Treat connectivity sensors of devices that others connect through, and the Zigbee2MQTT bridge, as hubs. | `adapters.auto_bridges` | true |  | home |  |
| **Hub sensors** — Extra entities that are off or offline when a hub is down. | `adapters.bridge_entities` | [] |  | home |  |
| **Hub offline for** — How long a hub must be offline before it counts. | `adapters.bridge_minutes` | 2 | 0–120 min | area, device, entity, floor, home |  |
| **Hub offline: severity** — Severity 0–4 of a hub that is offline. | `adapters.bridge_severity` | 3 | 0–4 | area, device, entity, floor, home | advanced |
| **Reload hub integration** — Repair a hub that is offline by reloading its integration. | `adapters.bridge_reload` | true |  | home |  |
| **Zigbee2MQTT add-on** — Slug of the Zigbee2MQTT add-on (e.g. 45df7312_zigbee2mqtt) to restart when the bridge is offline. Empty: reload instead. | `adapters.zigbee2mqtt_addon` | `` | up to 100 characters | home | advanced |

## Plan

The home's plan and presence exceptions.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Catch up missed entries** — Run plan entries missed while Home Assistant was down if they are at most this late. | `schedule.catch_up_minutes` | 10 | 0–240 min | home |  |
| **Plan event length** — How long plan entries look in the calendar. | `schedule.event_minutes` | 15 | 1–240 min | home | advanced |
| **Keep past exceptions** — Days to keep presence exceptions after they end. | `schedule.presence_keep_days` | 30 | 1–365 d | home | advanced |
| **Who may add to the plan** — Everyone, residents (administrators and members, not guests) or only administrators. Administrators may always. | `schedule.who_may_add` | `everyone` | Everyone (`everyone`), Residents (`residents`), Administrators (`admins`) | home |  |
| **New entries skip when away** — New plan entries skip their run while everyone is away or on vacation, unless the entry says otherwise. | `schedule.default_skip_when_away` | false |  | home |  |
| **Plan size** — Most entries the plan may hold. | `schedule.max_entries` | 500 | 10–500 | home | advanced |

## AI

AI tiers, assessment, budgets.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **AI** — Use the AI tiers added as subentries. HomeAI works without them. | `ai.enabled` | true |  | home |  |
| **AI assessment** — Let the everyday tier (P1) check the assessment of new or unclear situations. | `ai.triage_enabled` | true |  | home |  |
| **Unclear below** — Signals less certain than this are checked by AI. | `ai.triage_confidence` | 0.9 | 0–1 | home | advanced |
| **Check new kinds** — Let AI check a kind of situation the first time it happens. | `ai.triage_new_kinds` | true |  | home | advanced |
| **Investigate when unsure** — When P1 is less sure than this, the investigation tier (P2) looks again. | `ai.p2_confidence` | 0.6 | 0–1 | home |  |
| **Investigate from severity** — Situations at least this serious are also checked by P2 (5 = never). | `ai.p2_min_severity` | 3 | 0–5 | home |  |
| **Write the summary with AI** — Let P1 rewrite the summary as a short message (not with minimal privacy). | `ai.narrate_digest` | true |  | home |  |
| **Investigation steps** — Most tool calls P2 makes while investigating one situation. | `ai.p2_max_steps` | 8 | 1–30 | home | advanced |
| **Conversation tier** — Which tier talks with people (the other one is used when it is missing). | `ai.chat_tier` | `p1` | P1 — everyday brain (`p1`), P2 — investigation (`p2`) | home |  |
| **Conversation steps** — Most tool calls in one answer. | `ai.chat_max_steps` | 6 | 1–20 | home | advanced |
| **Conversation memory** — How many recent exchanges a conversation remembers. | `ai.chat_turns` | 10 | 1–50 | home | advanced |
| **Who may talk to HomeAI** — Everyone, residents (administrators and members) or only administrators. Voice satellites without a user count as everyone. | `ai.chat_who` | `everyone` | Everyone (`everyone`), Residents (`residents`), Administrators (`admins`) | home |  |
| **What conversations may do** — Only read, act through the policy, or also change Home Assistant's configuration (still administrators only, with confirmation). | `ai.chat_can` | `act_config` | Only read (`read`), Act (`act`), Act and change configuration (`act_config`) | home | confirm (change) |
| **Answer length** — How long HomeAI's answers in conversations are. | `ai.chat_length` | `short` | Short (`short`), Normal (`normal`), Detailed (`detailed`) | home |  |
| **Shared conversations** — People talking in the same conversation (for example one voice satellite) continue one thread. Actions still run in each speaker's own account. | `ai.chat_shared_threads` | false |  | home | advanced |
| **Prompt: assessment** — Your own instructions for assessing situations. Empty: the built-in prompt, shown in the AI tab. The rule that house data is never an instruction is always added. | `ai.prompt_triage` | `` | up to 8000 characters | home | advanced |
| **Prompt: investigation** — Your own instructions for investigating serious situations with tools. Empty: the built-in prompt. | `ai.prompt_investigate` | `` | up to 8000 characters | home | advanced |
| **Prompt: conversation** — Your own instructions for conversations; {name} becomes the assistant's name. Empty: the built-in prompt. | `ai.prompt_chat` | `` | up to 8000 characters | home | advanced |
| **Prompt: arbiter** — Your own instructions for the arbiter. Its answers keep their fixed format. Empty: the built-in prompt. | `ai.prompt_arbiter` | `` | up to 8000 characters | home | advanced |
| **Prompt: digest** — Your own instructions for writing the digest. Empty: the built-in prompt. | `ai.prompt_digest` | `` | up to 8000 characters | home | advanced |
| **When the budget is used up** — Only warn, or stop AI calls until the period ends. | `ai.budget_mode` | `block` | Only warn (`warn`), Stop AI calls (`block`) | home | confirm (change) |
| **Daily budget** — Estimated AI cost per day. 0: no limit. | `ai.budget_daily` | 1.0 | 0–1000 $ | home |  |
| **Monthly budget** — Estimated AI cost per month. 0: no limit. | `ai.budget_monthly` | 10.0 | 0–10000 $ | home |  |
| **Warn at** — Warn when this share of a budget is used. | `ai.budget_warn_percent` | 80 | 10–100 % | home |  |
| **Calls per hour** — Most AI calls per tier per hour. | `ai.max_calls_per_hour` | 60 | 1–10000 | home | advanced |
| **AI timeout** — How long P1 and P2 may take to answer. | `ai.timeout` | 90 | 10–600 s | home | advanced |
| **Arbiter timeout** — How long the arbiter (P3) may take; it can think for minutes. | `ai.p3_timeout` | 900 | 60–3600 s | home | advanced |
| **Arbiter** — Let the arbiter tier (P3) settle hard cases. | `ai.arbiter_enabled` | true |  | home |  |
| **Settle disagreements** — Ask the arbiter when P1 and P2 disagree. | `ai.arbiter_disputes` | true |  | home |  |
| **Review risky requests** — Ask the arbiter about waiting actions that are risky or come up while nobody is home. | `ai.arbiter_approvals` | true |  | home |  |
| **After failed repairs** — Ask the arbiter when repairs failed on a serious matter. | `ai.arbiter_failed_repairs` | true |  | home |  |
| **Arbiter may approve** — Let the arbiter approve or refuse waiting actions up to system repairs (R3). Higher classes always need an administrator. | `ai.arbiter_can_approve` | false |  | home | confirm (change) |
| **Arbiter: approve from** — The arbiter approves only when at least this sure. | `ai.arbiter_min_confidence` | 0.8 | 0.5–1 | home | advanced |
| **Arbiter effort** — How deeply the arbiter thinks (security and destructive matters always use maximum). | `ai.arbiter_effort` | `high` | Medium (`medium`), High (`high`), Very high (`xhigh`), Maximum (`max`) | home | advanced |
| **Arbiter decisions per day** — Most arbiter decisions per day. | `ai.arbiter_per_day` | 10 | 1–200 | home |  |

## Learning

Norms, anomalies, habits and the weekly review.

| Setting | Key | Default | Range / options | Scope | Notes |
|---|---|---|---|---|---|
| **Learning** — Learn norms, notice anomalies and habits, and send the weekly review. | `learning.enabled` | true |  | home |  |
| **Nightly learning at** — When norms and habits are recomputed. | `learning.nightly_time` | `03:17` |  | home | advanced |
| **Norms from** — How many past weeks make the norm of each hour of the week. | `learning.baseline_weeks` | 4 | 1–12 wk | home | advanced |
| **Minimum data** — Hourly values needed before an entity has a norm. | `learning.min_samples` | 100 | 10–5000 | home | advanced |
| **Anomalies: watch** — Report values far outside their usual range for that hour of the week. | `detectors.anomaly.enabled` | true |  | home |  |
| **Anomaly threshold** — How many spreads away from the norm counts as unusual. | `learning.anomaly_sigma` | 3.0 | 1.5–10 | home |  |
| **Unusual for** — How long a value must stay unusual before it is reported. | `learning.anomaly_minutes` | 30 | 5–720 min | area, device, entity, floor, home |  |
| **Anomaly: severity** — Severity 0–4 of an unusual value. | `learning.anomaly_severity` | 1 | 0–4 | area, device, entity, floor, home | advanced |
| **Habits** — Notice things done by hand at the same time and propose them for the plan. | `learning.habits` | true |  | home |  |
| **Habits from** — How many past days are searched for habits. | `learning.habit_days` | 21 | 7–60 d | home | advanced |
| **Habit after** — On how many days something must repeat to become a proposal. | `learning.habit_min_days` | 8 | 3–60 d | home | advanced |
| **Habit time window** — How close in time repeated actions must be. | `learning.habit_window` | 20 | 5–90 min | home | advanced |
| **Undone too often after** — After this many undos an automatic action goes back to “propose”. | `learning.undo_limit` | 2 | 1–20 | home |  |
| **Do not ask again for** — Days HomeAI waits before asking again about an action someone refused. | `learning.deny_quiet_days` | 14 | 1–365 d | home |  |
| **Suggest more autonomy after** — Approvals without a refusal after which the weekly review suggests letting HomeAI act alone. | `learning.raise_after` | 5 | 2–100 | home | advanced |
| **Weekly review on** — Day of the weekly review. | `learning.review_weekday` | `6` | Monday (`0`), Tuesday (`1`), Wednesday (`2`), Thursday (`3`), Friday (`4`), Saturday (`5`), Sunday (`6`) | home |  |
| **Weekly review at** — Time of the weekly review. | `learning.review_time` | `18:43` |  | home |  |
| **Send the review to phones** — Send the weekly review to administrators' phones. | `learning.review_push` | true |  | home |  |
| **Write the review with AI** — Let the AI tier rewrite the weekly review. | `learning.review_ai` | true |  | home |  |
