# Contributing to HomeAI

Thanks for helping. A few rules keep HomeAI usable in every home.

## Principles

- **No home-specific code.** No entity IDs, MQTT topics, person names or vendor quirks in the core.
  Discover everything from Home Assistant's registries; put hardware knowledge in an adapter.
- **Everything configurable from the UI.** Any value that changes behaviour (threshold, delay, limit,
  weight, channel, model, prompt) is declared in the settings registry, with a default, a range and
  translations in `en` and `pl`. Constants in code are only for things that never change.
- **The core works without AI.** A missing API key, an unreachable model or an exhausted budget must never
  stop detection, self-repair or notifications.
- **Every action goes through the policy.** Never call a service that changes something without the
  executor and the risk policy.
- **English** for code, comments and documentation. User-facing text lives in `translations/`.

## Development setup

Requirements: Python 3.14 and [uv](https://docs.astral.sh/uv/) (or pip).

```bash
uv venv -p 3.14
uv pip install -r requirements_test.txt
```

Run the checks before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest
python scripts/gen_settings_doc.py --check
```

The panel and the card are written in TypeScript with Lit and bundled with esbuild. The bundle is committed, so
rebuild it after changing `frontend/src`:

```bash
cd frontend
npm ci
npm run check
npm run build
```

After adding or changing a setting, regenerate the settings reference with `python scripts/gen_settings_doc.py`.
Triage evals against a real provider are described in [docs/ai.md](docs/ai.md).

## Pull requests

- Keep each pull request to one change, with tests.
- New settings come with UI fields and translations; new behaviour comes with scenario tests.
- CI runs hassfest, the HACS validation, ruff, pytest and the frontend build check; all must pass.
