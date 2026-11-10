"""The shipped blueprints are valid Home Assistant blueprints."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.util.yaml import load_yaml_dict
import pytest

BLUEPRINTS = sorted((Path(__file__).parent.parent / "blueprints/automation/homeai").glob("*.yaml"))


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_blueprint_is_valid(path: Path) -> None:
    blueprint = Blueprint(load_yaml_dict(str(path)), expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)
    assert blueprint.name.startswith("HomeAI")
    assert blueprint.inputs
