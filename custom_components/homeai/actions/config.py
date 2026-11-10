"""Configuration editing (R4): automations, scripts, scenes, helpers, labels, areas and dashboards.

Changes go through Home Assistant's own editor mechanisms (config REST views, helper and dashboard WebSocket
commands, registries), never by rewriting YAML. Saves are R4 (an administrator's yes), deletions R6. Before a
change the previous configuration is kept, so a change can be undone.

Operations are addressed as pseudo-services of the `config` domain, e.g. `config.automation_save` with
`{"id": ..., "config": {...}}` — so the policy, approvals, journal and logbook treat them like any action.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import area_registry as ar, label_registry as lr

from .local_api import LocalApi, LocalApiError

EDITORS = ("automation", "script", "scene")
HELPERS = (
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
)
OPERATIONS = frozenset(
    {f"{kind}_{op}" for kind in EDITORS for op in ("get", "save", "delete")}
    | {f"helper_{op}" for op in ("list", "save", "delete")}
    | {"label_save", "label_delete", "area_save", "area_delete", "dashboard_get", "dashboard_save"}
)


class ConfigError(Exception):
    """A configuration change was refused; the message says why."""


class ConfigEditor:
    def __init__(self, runtime: Any, api: LocalApi | None = None) -> None:
        self.rt = runtime
        self.hass = runtime.hass
        self.api = api or LocalApi(runtime)

    def supports(self, operation: str) -> bool:
        return operation in OPERATIONS

    async def run(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        """Perform an operation; returns {"result": ..., "previous": ...} (previous: for undo)."""
        kind, _, op = operation.rpartition("_")
        try:
            if kind in EDITORS:
                return await self._editor(kind, op, data)
            if kind == "helper":
                return await self._helper(op, data)
            if kind == "label":
                return self._label(op, data)
            if kind == "area":
                return self._area(op, data)
            if kind == "dashboard":
                return await self._dashboard(op, data)
        except LocalApiError as err:
            raise ConfigError(str(err)) from err
        raise ConfigError(f"unknown operation {operation}")

    # ——— Automations, scripts, scenes ———
    async def _editor(self, kind: str, op: str, data: dict[str, Any]) -> dict[str, Any]:
        config_id = str(data.get("id") or "").strip()
        if not config_id or "/" in config_id:
            raise ConfigError("id is required")
        path = f"/api/config/{kind}/config/{config_id}"
        previous = await self._get(path)
        if op == "get":
            return {"result": previous, "previous": None}
        if op == "delete":
            if previous is None:
                raise ConfigError("not found")
            await self.api.rest("DELETE", path)
            return {"result": {"deleted": config_id}, "previous": previous}
        config = data.get("config")
        if not isinstance(config, dict):
            raise ConfigError("config must be an object")
        if kind in ("automation", "scene"):
            config = {**config, "id": config_id}
        await self.api.rest("POST", path, config)
        return {"result": {"saved": config_id}, "previous": previous}

    async def _get(self, path: str) -> dict[str, Any] | None:
        try:
            return await self.api.rest("GET", path)
        except LocalApiError as err:
            if str(err).startswith("404"):
                return None
            raise

    async def restore(self, operation: str, data: dict[str, Any], previous: dict[str, Any] | None) -> None:
        """Undo: put the previous configuration back (or delete what was created)."""
        kind, _, _op = operation.rpartition("_")
        if kind in EDITORS:
            config_id = str(data["id"])
            path = f"/api/config/{kind}/config/{config_id}"
            if previous is None:
                await self.api.rest("DELETE", path)
            else:
                await self.api.rest("POST", path, previous)
            return
        raise ConfigError("this change cannot be undone automatically")

    # ——— Helpers ———
    async def _helper(self, op: str, data: dict[str, Any]) -> dict[str, Any]:
        domain = data.get("domain")
        if domain not in HELPERS:
            raise ConfigError(f"domain is one of {', '.join(HELPERS)}")
        if op == "list":
            return {"result": await self.api.ws({"type": f"{domain}/list"}), "previous": None}
        if op == "delete":
            item_id = data.get("item_id")
            await self.api.ws({"type": f"{domain}/delete", f"{domain}_id": item_id})
            return {"result": {"deleted": item_id}, "previous": None}
        fields = data.get("fields")
        if not isinstance(fields, dict):
            raise ConfigError("fields must be an object")
        if data.get("item_id"):
            result = await self.api.ws({"type": f"{domain}/update", f"{domain}_id": data["item_id"], **fields})
        else:
            result = await self.api.ws({"type": f"{domain}/create", **fields})
        return {"result": result, "previous": None}

    # ——— Labels and areas (registries) ———
    def _label(self, op: str, data: dict[str, Any]) -> dict[str, Any]:
        reg = lr.async_get(self.hass)
        if op == "delete":
            reg.async_delete(str(data["label_id"]))
            return {"result": {"deleted": data["label_id"]}, "previous": None}
        fields = {k: data[k] for k in ("name", "icon", "color", "description") if k in data}
        if data.get("label_id"):
            entry = reg.async_update(str(data["label_id"]), **fields)
        else:
            entry = reg.async_create(**fields)
        return {"result": {"label_id": entry.label_id, "name": entry.name}, "previous": None}

    def _area(self, op: str, data: dict[str, Any]) -> dict[str, Any]:
        reg = ar.async_get(self.hass)
        if op == "delete":
            reg.async_delete(str(data["area_id"]))
            return {"result": {"deleted": data["area_id"]}, "previous": None}
        fields = {k: data[k] for k in ("name", "icon", "floor_id", "aliases", "labels") if k in data}
        for key in ("aliases", "labels"):
            if key in fields:
                fields[key] = set(fields[key])
        entry = reg.async_update(str(data["area_id"]), **fields) if data.get("area_id") else reg.async_create(**fields)
        return {"result": {"area_id": entry.id, "name": entry.name}, "previous": None}

    # ——— Dashboards ———
    async def _dashboard(self, op: str, data: dict[str, Any]) -> dict[str, Any]:
        url_path = data.get("url_path")
        base: dict[str, Any] = {"type": "lovelace/config"}
        if url_path:
            base["url_path"] = url_path
        try:
            previous = await self.api.ws(base)
        except LocalApiError:
            previous = None
        if op == "get":
            return {"result": previous, "previous": None}
        config = data.get("config")
        if not isinstance(config, dict):
            raise ConfigError("config must be an object")
        save: dict[str, Any] = {"type": "lovelace/config/save", "config": config}
        if url_path:
            save["url_path"] = url_path
        await self.api.ws(save)
        return {"result": {"saved": url_path or "default"}, "previous": previous}
