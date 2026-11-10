"""Write docs/settings.md from the settings registry and the English texts.

python scripts/gen_settings_doc.py          # write
python scripts/gen_settings_doc.py --check  # exit 1 when the file is out of date
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.homeai.settings.definitions import build_registry  # noqa: E402

SCOPES = {
    "global": "home",
    "floor": "floor",
    "area": "area",
    "device": "device",
    "entity": "entity",
    "person": "person",
}


def render() -> str:
    texts = json.loads((ROOT / "custom_components/homeai/i18n/en.json").read_text(encoding="utf-8"))
    labels, sections, options = texts["settings"], texts["sections"], texts.get("options", {})
    registry = build_registry()
    lines = [
        "# Settings",
        "",
        "Every option HomeAI has, as shown in the HomeAI panel (Settings tab). Generated from the settings registry by",
        "`scripts/gen_settings_doc.py`; do not edit by hand.",
        "",
        "*Scope* says where a value can be set: for the whole home, or overridden for a floor, area, device, entity",
        "or person (the most specific value wins). *Confirm* marks changes that ask for confirmation because they",
        "lower protection or change something important.",
        "",
    ]
    for section in registry.sections():
        info = sections.get(section, {})
        lines += [f"## {info.get('label', section)}", "", info.get("description", ""), ""]
        lines += ["| Setting | Key | Default | Range / options | Scope | Notes |", "|---|---|---|---|---|---|"]
        for s in registry:
            if s.section != section:
                continue
            text = labels.get(s.key, {})
            if s.options:
                names = options.get(s.key, {})
                rng = ", ".join(f"{names.get(o, o)} (`{o}`)" for o in s.options)
            elif s.type.value in ("string", "text") and s.max is not None:
                rng = f"up to {int(s.max)} characters"
            elif s.min is not None or s.max is not None:
                rng = (
                    f"{s.min if s.min is not None else ''}–{s.max if s.max is not None else ''} {s.unit or ''}".strip()
                )
            else:
                rng = s.unit or ""
            default = json.dumps(s.default, ensure_ascii=False) if not isinstance(s.default, str) else f"`{s.default}`"
            if s.type.value in ("json",) or len(default) > 60:
                default = "see panel"
            scopes = ", ".join(SCOPES.get(x.value, x.value) for x in sorted(s.scopes, key=lambda x: x.value))
            notes = [n for n in ("advanced" if s.advanced else "", f"confirm ({s.confirm})" if s.confirm else "") if n]
            description = text.get("description", "").replace("|", "\\|")
            lines.append(
                f"| **{text.get('label', s.key)}** — {description} | `{s.key}` | {default} | {rng.replace('|', '/')} "
                f"| {scopes} | {', '.join(notes)} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    target = ROOT / "docs/settings.md"
    content = render()
    if "--check" in sys.argv:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            print("docs/settings.md is out of date: run python scripts/gen_settings_doc.py")
            return 1
        return 0
    target.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
