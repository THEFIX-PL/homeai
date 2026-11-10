"""HomeAI services (actions). Each stage adds its handlers to SERVICES."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
import voluptuous as vol

from ..const import DOMAIN


@dataclass(frozen=True, slots=True)
class ServiceDef:
    name: str
    handler: Callable[[Any, ServiceCall], Awaitable[ServiceResponse | None]]
    schema: vol.Schema
    response: SupportsResponse = SupportsResponse.NONE


SERVICES: list[ServiceDef] = []


def runtime_for_service(hass: HomeAssistant) -> Any:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


@callback
def async_register_services(hass: HomeAssistant) -> None:
    from . import service_actions, service_handlers  # noqa: F401 - handlers register themselves

    for svc in SERVICES:

        def make(svc: ServiceDef) -> Callable[[ServiceCall], Awaitable[ServiceResponse | None]]:
            async def handle(call: ServiceCall) -> ServiceResponse | None:
                return await svc.handler(runtime_for_service(hass), call)

            return handle

        hass.services.async_register(DOMAIN, svc.name, make(svc), schema=svc.schema, supports_response=svc.response)
