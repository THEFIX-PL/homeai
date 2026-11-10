"""Talk to this Home Assistant the way its own editors do: REST config views and WebSocket commands.

Requests are authenticated as the HomeAI system user (system refresh token, short-lived access tokens), so
Home Assistant validates every change exactly as it does for the UI, and the logbook shows HomeAI as the
author. The address is this instance on localhost (or `executor.local_url`).
"""

from __future__ import annotations

import itertools
from typing import Any

import aiohttp
from homeassistant.auth.models import TOKEN_TYPE_SYSTEM
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession


class LocalApiError(Exception):
    """A request to the local API failed; the message is HA's answer."""


class LocalApi:
    def __init__(
        self, runtime: Any, *, base_url: str | None = None, session: aiohttp.ClientSession | None = None
    ) -> None:
        self.rt = runtime
        self.hass: HomeAssistant = runtime.hass
        self._base_url = base_url
        self._session = session
        self._ids = itertools.count(1)

    def base_url(self) -> str:
        if self._base_url:
            return self._base_url.rstrip("/")
        configured = str(self.rt.settings.get("executor.local_url") or "").strip()
        if configured:
            return configured.rstrip("/")
        api = self.hass.config.api
        scheme = "https" if api and api.use_ssl else "http"
        port = api.port if api else 8123
        return f"{scheme}://127.0.0.1:{port}"

    def session(self) -> aiohttp.ClientSession:
        return self._session or async_get_clientsession(self.hass, verify_ssl=False)

    async def token(self) -> str:
        user = await self.hass.auth.async_get_user(self.rt.system_user_id) if self.rt.system_user_id else None
        if user is None:
            raise LocalApiError("no HomeAI user")
        refresh = next((t for t in user.refresh_tokens.values() if t.token_type == TOKEN_TYPE_SYSTEM), None)
        if refresh is None:
            refresh = await self.hass.auth.async_create_refresh_token(user)
        return self.hass.auth.async_create_access_token(refresh)

    async def rest(self, method: str, path: str, payload: Any = None) -> Any:
        headers = {"Authorization": f"Bearer {await self.token()}"}
        async with self.session().request(
            method, f"{self.base_url()}{path}", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            try:
                body = await resp.json(content_type=None)
            except ValueError:
                body = await resp.text()
            if resp.status >= 400:
                message = body.get("message") if isinstance(body, dict) else body
                raise LocalApiError(f"{resp.status}: {message}")
            return body

    async def ws(self, command: dict[str, Any]) -> Any:
        """Run one WebSocket command and return its result."""
        url = self.base_url().replace("http", "ws", 1) + "/api/websocket"
        async with self.session().ws_connect(url, timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
            hello = await ws.receive_json(timeout=10)
            if hello.get("type") != "auth_required":
                raise LocalApiError("unexpected greeting")
            await ws.send_json({"type": "auth", "access_token": await self.token()})
            auth = await ws.receive_json(timeout=10)
            if auth.get("type") != "auth_ok":
                raise LocalApiError("auth failed")
            msg_id = next(self._ids)
            await ws.send_json({**command, "id": msg_id})
            while True:
                msg = await ws.receive_json(timeout=30)
                if msg.get("id") == msg_id and msg.get("type") == "result":
                    if not msg.get("success"):
                        raise LocalApiError(str((msg.get("error") or {}).get("message")))
                    return msg.get("result")
