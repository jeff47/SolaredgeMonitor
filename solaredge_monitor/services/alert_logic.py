# solaredge_monitor/services/alert_logic.py

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List

from solaredge_monitor.models.system_health import InverterHealth, SystemHealth


@dataclass
class Alert:
    inverter_name: str
    serial: str
    message: str
    status: int
    pac_w: float | None


def _snapshot_details(inv: InverterHealth) -> tuple[str, int, float | None]:
    snap = inv.reading
    serial = snap.serial if snap else "unknown"
    status = snap.status if snap and snap.status is not None else -1
    pac = snap.pac_w if snap else None
    return serial, status, pac


def evaluate_alerts(health: SystemHealth, now: datetime | None = None) -> List[Alert]:
    """Convert health-evaluator results into user-facing alerts."""

    alerts: list[Alert] = []
    bad_inverters = [inv for inv in health.per_inverter.values() if not inv.inverter_ok]

    for inv in bad_inverters:
        serial, status, pac = _snapshot_details(inv)
        alerts.append(
            Alert(
                inverter_name=inv.name,
                serial=serial,
                message=inv.reason or "Unknown inverter fault",
                status=status,
                pac_w=pac,
            )
        )

    if not bad_inverters and not health.system_ok:
        alerts.append(
            Alert(
                inverter_name="SYSTEM",
                serial="SYSTEM",
                message=health.reason or "System health failure",
                status=-1,
                pac_w=None,
            )
        )

    return alerts
