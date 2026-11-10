"""Shared fixtures for HomeAI tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Let Home Assistant load integrations from custom_components in every test."""
    yield
