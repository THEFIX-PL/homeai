"""The smart home itself: unresponsive devices, failing integrations, sign-in requests, Repairs issues, backups,
updates, log errors, failing automations and the internet connection."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_REAUTH, ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util

from ...world import Role
from ..base import Category, DetectionContext, Detector, Need, Signal
from .util import UNAVAILABLE, clock, critical, name, state, where

FAILED_STATES = {
    ConfigEntryState.SETUP_ERROR: "setup_error",
    ConfigEntryState.SETUP_RETRY: "setup_retry",
    ConfigEntryState.MIGRATION_ERROR: "migration_error",
    ConfigEntryState.FAILED_UNLOAD: "failed_unload",
}
NOT_RELOADABLE = frozenset({"homeai", "backup", "mobile_app"})


def integration_name(ctx: DetectionContext, domain: str, fallback: str = "") -> str:
    try:
        return async_get_loaded_integration(ctx.hass, domain).name
    except Exception:
        return fallback or domain


def device_tags(ctx: DetectionContext, device_id: str) -> frozenset[str]:
    """Network family of a device, for correlation with a failing bridge or a missing internet connection."""
    device = ctx.world.devices.get(device_id)
    if device is None:
        return frozenset()
    tags: set[str] = set()
    for domain, ident in device.identifiers:
        if domain == "zha" or (domain == "mqtt" and str(ident).startswith("zigbee2mqtt_")):
            tags.add("zigbee")
        if domain == "matter":
            tags.add("matter")
    if device.via_device_id:
        tags.add(f"via:{device.via_device_id}")  # explained by its hub being offline
    entry = ctx.hass.config_entries.async_get_entry(device.config_entry_id) if device.config_entry_id else None
    if entry is not None:
        try:
            iot_class = async_get_loaded_integration(ctx.hass, entry.domain).iot_class or ""
        except Exception:
            iot_class = ""
        if iot_class.startswith("cloud"):
            tags.add("cloud")
    return frozenset(tags)


class AvailabilityDetector(Detector):
    """Devices whose every visible entity has been unavailable longer than the configured time."""

    key = "availability"
    roles = (Role.CONTROLLABLE,)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out: list[Signal] = []
        down_by_entry: dict[str, list[str]] = {}
        alive_by_entry: dict[str, int] = {}
        for device_id, device in ctx.world.devices.items():
            entities = [e for e in device.entities if (info := ctx.world.entity(e)) and not info.hidden]
            states = [s for e in entities if (s := state(ctx, e)) is not None]
            entry = device.config_entry_id
            if not states:
                continue
            if not all(s.state == "unavailable" for s in states):
                if entry:
                    alive_by_entry[entry] = alive_by_entry.get(entry, 0) + 1
                continue
            if ctx.world.device_has_label(device_id, "label_personal"):
                continue
            since = max(s.last_changed for s in states)
            minutes = float(ctx.settings.get("detectors.availability.minutes", ctx.world.target(entities[0])))
            if ctx.now - since < timedelta(minutes=minutes):
                continue
            if entry:
                down_by_entry.setdefault(entry, []).append(device_id)
            severity = (
                4
                if any(critical(ctx, e) for e in entities) or ctx.world.device_has_label(device_id, "label_critical")
                else int(ctx.settings.get("detectors.availability.severity", ctx.world.target(entities[0])))
            )
            out.append(
                Signal(
                    id=f"unavailable:{device_id}",
                    detector=self.key,
                    kind="device_unavailable",
                    category=Category.SYSTEM,
                    severity=severity,
                    entities=tuple(sorted(entities)),
                    device_id=device_id,
                    area_id=device.area_id,
                    since=since,
                    data={"name": device.name, "where": ctx.world.area_name(device.area_id), "since": clock(since)},
                    need=Need.MEMBER,
                    tags=device_tags(ctx, device_id),
                )
            )
        # all devices of one working integration down → one situation with an automatic reload attempt
        for i, signal in enumerate(out):
            entry_id = None
            for e, devices in down_by_entry.items():
                if signal.device_id in devices:
                    entry_id = e
            if entry_id is None or alive_by_entry.get(entry_id):
                continue
            entry = ctx.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain in NOT_RELOADABLE or entry.state is not ConfigEntryState.LOADED:
                continue
            out[i] = replace(
                signal,
                root=f"entry:{entry_id}",
                data={**signal.data, "integration": integration_name(ctx, entry.domain, entry.title)},
                repair={"playbook": "reload_after_outage", "entry_id": entry_id},
            )
        return out


class IntegrationsDetector(Detector):
    """Config entries that failed to set up, need a new sign-in, and open issues in Repairs."""

    key = "integrations"

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out: list[Signal] = []
        for entry in ctx.hass.config_entries.async_entries():
            if entry.disabled_by or entry.source == SOURCE_IGNORE:
                continue
            title = integration_name(ctx, entry.domain, entry.title)
            if any(entry.async_get_active_flows(ctx.hass, {SOURCE_REAUTH})):
                out.append(
                    Signal(
                        id=f"reauth:{entry.entry_id}",
                        detector=self.key,
                        kind="integration_reauth",
                        category=Category.SYSTEM,
                        severity=int(ctx.settings.get("detectors.integrations.severity")),
                        data={"name": title, "account": entry.title},
                        need=Need.ADMIN,
                        root=f"entry:{entry.entry_id}",
                    )
                )
                continue
            status = FAILED_STATES.get(entry.state)
            if status is None:
                continue
            repair = None
            if entry.domain not in NOT_RELOADABLE and entry.state in (
                ConfigEntryState.SETUP_ERROR,
                ConfigEntryState.SETUP_RETRY,
            ):
                repair = {
                    "playbook": "wait_then_reload" if status == "setup_retry" else "reload_entry",
                    "entry_id": entry.entry_id,
                }
            out.append(
                Signal(
                    id=f"integration:{entry.entry_id}",
                    detector=self.key,
                    kind=f"integration_{status}",
                    category=Category.SYSTEM,
                    severity=int(ctx.settings.get("detectors.integrations.severity")),
                    data={"name": title, "reason": str(getattr(entry, "reason", "") or "")[:200]},
                    need=Need.ADMIN,
                    root=f"entry:{entry.entry_id}",
                    repair=repair,
                )
            )
        if ctx.settings.get("detectors.integrations.repairs"):
            issues = [i for i in ir.async_get(ctx.hass).issues.values() if i.active and i.dismissed_version is None]
            if issues:
                domains = sorted({i.domain for i in issues})
                out.append(
                    Signal(
                        id="repairs",
                        detector=self.key,
                        kind="repairs_issues",
                        category=Category.SYSTEM,
                        severity=int(ctx.settings.get("detectors.integrations.repairs_severity")),
                        data={"count": len(issues), "domains": [integration_name(ctx, d) for d in domains]},
                        need=Need.ADMIN,
                    )
                )
        return out


class BackupDetector(Detector):
    """Automatic backups that failed, are too old, or did not reach every backup location."""

    key = "backups"

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out: list[Signal] = []
        entities = [e for e in ctx.world.entities.values() if e.platform == "backup"]

        def by_key(key: str) -> str | None:
            return next((e.entity_id for e in entities if e.translation_key == key), None)

        last_ok_id = by_key("last_successful_automatic_backup")
        event_id = by_key("automatic_backup_event")
        last_ok_state = state(ctx, last_ok_id) if last_ok_id else None
        last_ok = (
            dt_util.parse_datetime(last_ok_state.state)
            if last_ok_state and last_ok_state.state not in UNAVAILABLE
            else None
        )
        event = state(ctx, event_id) if event_id else None
        event_time = dt_util.parse_datetime(event.state) if event and event.state not in UNAVAILABLE else None
        running = bool(event and event.attributes.get("event_type") == "in_progress")
        repair = {"playbook": "retry_backup", "paused": running}
        if (
            event
            and event.attributes.get("event_type") == "failed"
            and event_time
            and (last_ok is None or event_time > last_ok)
        ):
            out.append(
                Signal(
                    id="backup_failed",
                    detector=self.key,
                    kind="backup_failed",
                    category=Category.SYSTEM,
                    severity=int(ctx.settings.get("detectors.backups.severity")),
                    since=event_time,
                    data={"reason": str(event.attributes.get("failed_reason") or ""), "last_ok": clock(last_ok)},
                    need=Need.ADMIN,
                    root="backup",
                    repair=repair,
                )
            )
        elif last_ok_id and (
            last_ok is None
            or ctx.now - last_ok > timedelta(hours=float(ctx.settings.get("detectors.backups.max_age_hours")))
        ):
            out.append(
                Signal(
                    id="backup_stale",
                    detector=self.key,
                    kind="backup_stale",
                    category=Category.SYSTEM,
                    severity=int(ctx.settings.get("detectors.backups.severity")),
                    data={"last_ok": clock(last_ok)},
                    need=Need.ADMIN,
                    root="backup",
                    repair=repair,
                )
            )
        for agent in ctx.system.backup_agents_failed:
            out.append(
                Signal(
                    id=f"backup_agent:{agent}",
                    detector=self.key,
                    kind="backup_agent",
                    category=Category.SYSTEM,
                    severity=int(ctx.settings.get("detectors.backups.severity")),
                    data={
                        "agent": agent.split(".", 1)[0].replace("_", " ").title()
                        if agent != "backup.local"
                        else "local"
                    },
                    need=Need.ADMIN,
                    root="backup",
                )
            )
        return out


class UpdatesDetector(Detector):
    key = "updates"
    roles = (Role.UPDATE,)

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        pending = []
        for entity_id in sorted(ctx.world.with_role(Role.UPDATE)):
            s = state(ctx, entity_id)
            if s is not None and s.state == "on":
                pending.append(name(ctx, entity_id))
        if not pending:
            return []
        return [
            Signal(
                id="updates",
                detector=self.key,
                kind="updates",
                category=Category.MAINTENANCE,
                severity=int(ctx.settings.get("detectors.updates.severity")),
                data={"count": len(pending), "names": pending[:10]},
                need=Need.ADMIN,
            )
        ]


class LogDetector(Detector):
    """Errors in Home Assistant's log within the last day, and automations whose last run failed."""

    key = "log"

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        out: list[Signal] = []
        horizon = ctx.now.timestamp() - float(ctx.settings.get("detectors.log.window_hours")) * 3600
        errors = [
            r
            for r in ctx.system.log
            if r.get("level") in ("ERROR", "CRITICAL")
            and (r.get("timestamp") or 0) > horizon
            and not str(r.get("name", "")).startswith("custom_components.homeai")
        ]
        if errors and int(ctx.settings.get("detectors.log.min_errors")) <= len(errors):
            newest = max(errors, key=lambda r: r.get("timestamp") or 0)
            message = (newest.get("message") or [""])[0]
            out.append(
                Signal(
                    id="log_errors",
                    detector=self.key,
                    kind="log_errors",
                    category=Category.SYSTEM,
                    severity=int(ctx.settings.get("detectors.log.severity")),
                    data={"count": len(errors), "message": str(message)[:160]},
                    need=Need.ADMIN,
                )
            )
        if ctx.settings.get("detectors.log.automations"):
            latest: dict[str, dict] = {}
            for t in ctx.system.traces:
                start = (t.get("timestamp") or {}).get("start")
                start = dt_util.parse_datetime(start) if isinstance(start, str) else start
                if start is None:
                    continue
                key = str(t.get("item_id"))
                if key not in latest or start > latest[key]["_start"]:
                    latest[key] = {**t, "_start": start}
            automations = {
                str(s.attributes.get("id")): s
                for s in ctx.hass.states.async_all("automation")
                if s.attributes.get("id")
            }
            for item_id, t in latest.items():
                failed = t.get("error") or t.get("script_execution") in ("error", "aborted")
                if not failed or ctx.now - t["_start"] > timedelta(
                    hours=float(ctx.settings.get("detectors.log.window_hours"))
                ):
                    continue
                s = automations.get(item_id)
                entity_id = s.entity_id if s else f"automation.{item_id}"
                out.append(
                    Signal(
                        id=f"automation:{item_id}",
                        detector=self.key,
                        kind="automation_error",
                        category=Category.SYSTEM,
                        severity=int(ctx.settings.get("detectors.log.automation_severity")),
                        entities=(entity_id,) if s else (),
                        since=t["_start"],
                        data={
                            "name": s.name if s else item_id,
                            "error": str(t.get("error") or "")[:160],
                            "when": clock(t["_start"]),
                        },
                        need=Need.ADMIN,
                    )
                )
        return out


class InternetDetector(Detector):
    """The home's internet connection, from a configured entity or the first Ping binary sensor."""

    key = "internet"
    roles = (Role.CONNECTIVITY,)
    watch_settings = ("detectors.internet.entity",)

    def _entity(self, ctx: DetectionContext) -> str | None:
        configured = ctx.settings.get("detectors.internet.entity")
        if configured:
            return str(configured)
        candidates = sorted(
            e.entity_id for e in ctx.world.entities.values() if e.platform == "ping" and e.domain == "binary_sensor"
        )
        return candidates[0] if candidates else None

    def evaluate(self, ctx: DetectionContext) -> list[Signal]:
        entity_id = self._entity(ctx)
        s = state(ctx, entity_id) if entity_id else None
        if s is None or s.state != "off":
            return []
        if ctx.now - s.last_changed < timedelta(minutes=float(ctx.settings.get("detectors.internet.minutes"))):
            return []
        return [
            Signal(
                id="internet",
                detector=self.key,
                kind="internet_down",
                category=Category.SYSTEM,
                severity=int(ctx.settings.get("detectors.internet.severity")),
                entities=(entity_id,),
                since=s.last_changed,
                data={"since": clock(s.last_changed), "where": where(ctx, entity_id)},
                need=Need.MEMBER,
                root="internet",
                suppresses=frozenset({"cloud"}),
            )
        ]
