"""WebSocket API for the HomeAI panel and cards (`homeai/*`)."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import importlib
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
import voluptuous as vol

from .. import i18n
from ..const import DOMAIN
from ..settings import SettingError, parse_scope_key

COMMANDS: list[Callable[..., Any]] = []


def runtime_of(hass: HomeAssistant) -> Any:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    return None


def command(schema: dict[Any, Any], *, admin: bool = False, is_async: bool = False) -> Callable:
    """Register a `homeai/...` command; handlers receive (hass, connection, msg, runtime)."""

    def decorator(func: Callable) -> Callable:
        if is_async:

            @wraps(func)
            async def handler(
                hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
            ) -> None:
                rt = runtime_of(hass)
                if rt is None:
                    connection.send_error(msg["id"], "not_loaded", "HomeAI is not loaded")
                    return
                try:
                    await func(hass, connection, msg, rt)
                except SettingError as err:
                    connection.send_error(msg["id"], "invalid_format", str(err))

            wrapped: Any = websocket_api.async_response(handler)
        else:

            @wraps(func)
            def handler(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
                rt = runtime_of(hass)
                if rt is None:
                    connection.send_error(msg["id"], "not_loaded", "HomeAI is not loaded")
                    return
                try:
                    func(hass, connection, msg, rt)
                except SettingError as err:
                    connection.send_error(msg["id"], "invalid_format", str(err))

            wrapped = callback(handler)
        if admin:
            wrapped = websocket_api.require_admin(wrapped)
        wrapped = websocket_api.websocket_command(schema)(wrapped)
        COMMANDS.append(wrapped)
        return wrapped

    return decorator


@callback
def async_register(hass: HomeAssistant) -> None:
    from .registry import MODULES

    for module in MODULES:  # each module registers its commands on import
        importlib.import_module(f".{module}", __package__)
    for cmd in COMMANDS:
        websocket_api.async_register_command(hass, cmd)


def user_name(hass: HomeAssistant, connection: websocket_api.ActiveConnection) -> str:
    for state in hass.states.async_all("person"):
        if state.attributes.get("user_id") == connection.user.id:
            return state.name
    return connection.user.name or connection.user.id


def lang_of(rt: Any, msg: dict[str, Any]) -> str:
    requested = msg.get("language")
    return requested if requested in i18n.SUPPORTED else rt.language


def scope_from(msg: dict[str, Any]) -> str:
    skey = msg.get("scope") or "global"
    parse_scope_key(skey)
    return skey


SCOPE = vol.Optional("scope", default="global")
LANG = vol.Optional("language")
TYPE = vol.Required("type")
