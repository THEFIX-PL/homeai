# HomeAI

Home intelligence for [Home Assistant](https://www.home-assistant.io/). HomeAI notices what changes in your
home, decides what to do about it, fixes what it can on its own, and tells you only when a person is needed.

> **Status: early development.** This version only installs the integration skeleton. It does not do
> anything in your home yet. Follow the [roadmap](#roadmap) below.

## What HomeAI will do

- **Works without AI.** Detection, situations, self-repair playbooks, scheduling and notifications run in
  plain code. AI adds judgement for unclear cases, conversation, planning and learning.
- **Works in any home.** Rooms, devices, people and phones are discovered from Home Assistant's registries.
  Nothing is hard-coded to one house; knowledge about specific hardware lives in optional adapters.
- **Three optional AI tiers, each over an API:**
  - a small, cheap "brain" for constant triage and simple requests (a local model through Ollama, or a
    low-cost cloud model);
  - an expert model for investigating problems with tools, complex conversations, planning and writing
    automations;
  - an arbiter model for the rare, hardest decisions, working from a prepared decision dossier.
- **One risk policy for every action.** Autonomous actions run as a dedicated `HomeAI` user, are verified,
  can be undone, and are logged. Safety-critical actions never run without a person.
- **Everything configurable from the UI.** Every threshold, delay, limit, channel, model and prompt has a
  field in the HomeAI panel, with sensible defaults.
- **Notifications that escalate sensibly.** Quiet hours, presence-aware targeting, acknowledgements, and an
  escalation ladder per severity.

## Requirements

- Home Assistant **2026.11** or newer.

## Installation

HomeAI is not in the default Marketplace catalog yet. Until it is:

1. In Home Assistant, open the **Marketplace** and add `https://github.com/THEFIX-PL/homeai` as a custom
   repository with the category **Integration**.
2. Install **HomeAI**, then add it under **Settings → Devices & services**.

Manual installation: copy `custom_components/homeai` into your Home Assistant `config/custom_components`
folder and restart Home Assistant.

## Roadmap

| Milestone | Scope |
|---|---|
| M1 | Repository, CI, setup wizard, settings registry and settings panel, incremental world model, diagnostics |
| M2 | Generic detectors, situation engine with correlation, deterministic triage ("who is needed"), notification router |
| M3 | Risk policy, executor with the `HomeAI` user, verification and undo, self-repair playbooks, adapters, scheduler |
| M4 | AI providers (Anthropic, OpenAI-compatible, Ollama), tiers, budgets, escalation, triage on the brain tier, evaluation suite |
| M5 | Expert agent with tools: investigation, conversation, planning, repair; HomeAI LLM API; panel and cards |
| M6 | Arbiter tier: decision dossiers, asynchronous decisions, human approval |
| M7 | Learning: baselines and anomalies, habit-based proposals, calibration from feedback, weekly review |
| M8 | Documentation, 1.0 release, submission to the default catalog |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). To report a security issue, see
[SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE).
