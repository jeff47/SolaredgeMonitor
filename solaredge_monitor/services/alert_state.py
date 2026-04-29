from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.services.alert_logic import Alert, evaluate_alerts
from solaredge_monitor.models.system_health import SystemHealth


@dataclass
class RecoveryNotification:
    inverter_name: str
    serial: str
    fault_code: str
    message: str
    resolved_at: datetime
    first_seen: Optional[datetime] = None


class AlertStateManager:
    """
    Aggregates all alert sources and applies suppression/combination rules.
    Future enhancements (e.g., quiet hours, deduping) can live here while
    main.py stays thin.
    """

    def __init__(
        self,
        log,
        *,
        state: AppState | None = None,
        consecutive_required: int = 1,
        consecutive_recovery_required: int = 1,
        identical_alert_gate_minutes: int = 60,
        repeat_alert_interval_minutes: int = 12 * 60,
    ):
        self.log = log
        self.state = state
        self.consecutive_required = max(1, int(consecutive_required))
        self.consecutive_recovery_required = max(1, int(consecutive_recovery_required))
        self.identical_alert_gate_minutes = max(1, int(identical_alert_gate_minutes))
        self.repeat_alert_interval_minutes = max(1, int(repeat_alert_interval_minutes))

    def _load_counters(self) -> dict[str, int]:
        if not self.state:
            return {}
        return {
            key: vals[0]
            for key, vals in self.state.get_health_counters().items()
        }

    def _save_counters(
        self,
        counters: dict[str, int],
        recovery_counters: dict[str, int],
        now: datetime,
    ) -> None:
        if self.state is None:
            return
        merged: dict[str, tuple[int, int]] = {}
        names = set(counters.keys()) | set(recovery_counters.keys())
        for name in names:
            merged[name] = (int(counters.get(name, 0)), int(recovery_counters.get(name, 0)))
        self.state.upsert_health_counters(merged, updated_at=now.isoformat())

    def _load_recovery_counters(self) -> dict[str, int]:
        if not self.state:
            return {}
        return {
            key: vals[1]
            for key, vals in self.state.get_health_counters().items()
        }

    def _load_incidents(self) -> dict[str, dict]:
        if not self.state:
            return {}
        return self.state.get_open_incidents()

    def _save_incidents(self, incidents: dict[str, dict]) -> None:
        # DB-backed incidents are persisted incrementally as they change.
        _ = incidents

    def _update_counters(
        self,
        counters: dict[str, int],
        recovery_counters: dict[str, int],
        health: SystemHealth,
    ) -> bool:
        changed = False
        for name, inv_state in health.per_inverter.items():
            key = name
            if inv_state.inverter_ok:
                if counters.get(key, 0) != 0:
                    counters[key] = 0
                    changed = True
                prev_recovery = recovery_counters.get(key, 0)
                recovery_counters[key] = prev_recovery + 1
                if recovery_counters[key] != prev_recovery:
                    changed = True
                continue
            if recovery_counters.get(key, 0) != 0:
                recovery_counters[key] = 0
                changed = True
            prev = counters.get(key, 0)
            counters[key] = prev + 1
            if counters[key] != prev:
                changed = True
        return changed

    def _filter_by_consecutive(
        self,
        counters: dict[str, int],
        alerts: List[Alert],
    ) -> List[Alert]:
        if self.consecutive_required <= 1:
            return alerts

        gated: list[Alert] = []
        for alert in alerts:
            if alert.inverter_name == "SYSTEM":
                gated.append(alert)
                continue
            count = counters.get(alert.inverter_name, 0)
            if count >= self.consecutive_required:
                gated.append(alert)
        return gated

    def _parse_dt(self, raw: object) -> Optional[datetime]:
        if not raw or not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _should_emit_repeat(self, now: datetime, incident: dict) -> bool:
        last_alerted = self._parse_dt(incident.get("last_alerted"))
        if last_alerted is None:
            return True
        alert_count = int(incident.get("alert_count", 1) or 1)
        interval_minutes = (
            self.identical_alert_gate_minutes
            if alert_count <= 1
            else self.repeat_alert_interval_minutes
        )
        return (now - last_alerted).total_seconds() >= (interval_minutes * 60)

    def _format_recovery_message(self, incident: dict, resolved_at: datetime) -> str:
        previous = incident.get("message") or "fault cleared"
        first_seen = self._parse_dt(incident.get("first_seen"))
        if first_seen is None:
            return f"Recovered: {previous}"
        duration = resolved_at - first_seen
        return f"Recovered after {duration}: {previous}"

    def _incident_source(self, incident: dict) -> str:
        fault_code = str(incident.get("fault_code") or "")
        if fault_code == "optimizer_mismatch":
            return "optimizer"
        if fault_code == "system_message":
            return "extra"
        return "health"

    def _persist_incident_open_or_update(
        self,
        *,
        key: str,
        incident: dict,
        source: str,
        event_type: str,
        now: datetime,
    ) -> None:
        if not self.state:
            return
        self.state.upsert_open_incident(
            incident_key=key,
            inverter_name=key,
            serial=str(incident.get("serial") or key),
            fault_code=str(incident.get("fault_code") or "unknown_fault"),
            fingerprint=str(incident.get("fingerprint") or ""),
            message=str(incident.get("message") or ""),
            first_seen=str(incident.get("first_seen") or now.isoformat()),
            last_seen=str(incident.get("last_seen") or now.isoformat()),
            last_alerted=incident.get("last_alerted"),
            alert_count=int(incident.get("alert_count", 0) or 0),
            source=source,
            event_type=event_type,
            event_ts=now.isoformat(),
            payload={
                "status": incident.get("status"),
                "source": source,
                "fault_code": incident.get("fault_code"),
            },
        )

    def build_notification_batch(
        self,
        *,
        now: datetime,
        health: Optional[SystemHealth],
        optimizer_mismatches: Optional[Iterable[Tuple[str, int, Optional[int]]]] = None,
        extra_messages: Optional[Iterable[str]] = None,
    ) -> tuple[List[Alert], List[RecoveryNotification]]:
        tx = self.state.transaction() if self.state else None
        if tx is None:
            from contextlib import nullcontext
            tx = nullcontext()
        with tx:
            alerts: list[Alert] = []
            recoveries: list[RecoveryNotification] = []

            health_evaluated = health is not None
            optimizer_evaluated = optimizer_mismatches is not None
            extra_evaluated = extra_messages is not None
            optimizer_mismatches_list = list(optimizer_mismatches or [])
            extra_messages_list = list(extra_messages or [])

            counters = self._load_counters()
            recovery_counters = self._load_recovery_counters()
            incidents = self._load_incidents()
            counters_changed = False
            recovery_counters_changed = False
            incidents_changed = False

            if health:
                changed = self._update_counters(counters, recovery_counters, health)
                counters_changed = changed or counters_changed
                recovery_counters_changed = changed or recovery_counters_changed
                health_alerts = evaluate_alerts(health, now)
                alerts.extend(self._filter_by_consecutive(counters, health_alerts))

            for name, expected, actual in optimizer_mismatches_list:
                actual_txt = "unknown" if actual is None else str(actual)
                alerts.append(
                    Alert(
                        inverter_name=name,
                        serial="CLOUD",
                        fault_code="optimizer_mismatch",
                        message=f"Optimizer count mismatch (expected {expected}, cloud={actual_txt})",
                        status=-1,
                        pac_w=None,
                    )
                )

            for msg in extra_messages_list:
                alerts.append(
                    Alert(
                        inverter_name="SYSTEM",
                        serial="SYSTEM",
                        fault_code="system_message",
                        message=msg,
                        status=-1,
                        pac_w=None,
                    )
                )

            emitted: list[Alert] = []
            current_names = {alert.inverter_name for alert in alerts}
            health_names = set(health.per_inverter.keys()) if health is not None else set()

            for alert in alerts:
                key = alert.inverter_name
                fingerprint = alert.fault_code
                incident = incidents.get(key)
                if not incident or incident.get("fingerprint") != fingerprint:
                    incidents[key] = {
                        "fingerprint": fingerprint,
                        "serial": alert.serial,
                        "fault_code": alert.fault_code,
                        "message": alert.message,
                        "status": alert.status,
                        "first_seen": now.isoformat(),
                        "last_seen": now.isoformat(),
                        "last_alerted": now.isoformat(),
                        "alert_count": 1,
                    }
                    incidents_changed = True
                    emitted.append(alert)
                    self._persist_incident_open_or_update(
                        key=key,
                        incident=incidents[key],
                        source=self._incident_source(incidents[key]),
                        event_type="opened",
                        now=now,
                    )
                    continue

                incident["serial"] = alert.serial
                incident["fault_code"] = alert.fault_code
                incident["message"] = alert.message
                incident["status"] = alert.status
                incident["last_seen"] = now.isoformat()

                if self._should_emit_repeat(now, incident):
                    incident["last_alerted"] = now.isoformat()
                    incident["alert_count"] = int(incident.get("alert_count", 1) or 1) + 1
                    emitted.append(alert)
                    self._persist_incident_open_or_update(
                        key=key,
                        incident=incident,
                        source=self._incident_source(incident),
                        event_type="repeat_alert",
                        now=now,
                    )
                incidents[key] = incident
                incidents_changed = True

            for key in list(incidents.keys()):
                if key in current_names:
                    continue
                incident = incidents[key]
                source = self._incident_source(incident)
                if source == "health":
                    if not health_evaluated or key not in health_names:
                        continue
                    if recovery_counters.get(key, 0) < self.consecutive_recovery_required:
                        continue
                elif source == "optimizer":
                    if not optimizer_evaluated:
                        continue
                elif source == "extra":
                    if not extra_evaluated:
                        continue
                incident = incidents.pop(key)
                recoveries.append(
                    RecoveryNotification(
                        inverter_name=key,
                        serial=str(incident.get("serial") or key),
                        fault_code=str(incident.get("fault_code") or "unknown_recovery"),
                        message=self._format_recovery_message(incident, now),
                        resolved_at=now,
                        first_seen=self._parse_dt(incident.get("first_seen")),
                    )
                )
                if self.state:
                    self.state.close_incident(
                        incident_key=key,
                        resolved_at=now.isoformat(),
                        recovery_message=recoveries[-1].message,
                        event_type="recovered",
                        payload={
                            "source": source,
                            "fault_code": incident.get("fault_code"),
                        },
                    )
                incidents_changed = True

            if counters_changed or recovery_counters_changed:
                self._save_counters(counters, recovery_counters, now)
            if incidents_changed:
                self._save_incidents(incidents)

            has_active_health_incident = any(
                self._incident_source(inc) == "health"
                for inc in incidents.values()
            )
            return emitted, recoveries, has_active_health_incident
