# Releasing

Steps for a release. Items marked *(owner)* need the repository owner.

1. *(owner)* Repository settings on GitHub: a description (for example “Home intelligence for Home Assistant:
   notices, decides, fixes, and tells people only when needed”) and topics `home-assistant`, `hacs`,
   `homeassistant`, `integration`, `home-automation`. HACS validation checks both.
2. CI green on the release commit: ruff, pytest, frontend build check, hassfest, HACS validation.
3. Versions match: `manifest.json`, `const.py`, `pyproject.toml`, `frontend/package.json`; `CHANGELOG.md` has the
   section for the version.
4. `python scripts/gen_settings_doc.py --check` passes and the committed frontend bundle is current.
5. Test on a Home Assistant 2026.11 instance (for example in Docker): install from the branch, run the setup
   wizard, add a P1 tier, trigger a test signal with `homeai.report_signal`, check the panel, a phone
   notification with actions, approvals and undo.
6. *(owner)* Merge, tag `vX.Y.Z` on `main` and publish a GitHub release with the changelog section.
7. *(owner)* For the default catalog: open a pull request to `hacs/default` adding `THEFIX-PL/homeai` to the
   `integration` list (the repository must be public and have a release).
