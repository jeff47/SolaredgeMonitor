# solaredge_monitor/services/alert_logic.py

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List
from solaredge_monitor.models.inverter import InverterSnapshot


# Rough SolarEdge status codes
STATUS_TEXT = {
    1: "Off",
    2: "Sleeping",
    3: "Grid Monitoring",
    4: "Producing",
    5: "Producing (Limited)",
    6: "Shutdown",
    7: "Fault",
    8: "Standby",
}


@dataclass
class Alert:
    inverter_name: str
    serial: str
    message: str
    status: int
    pac_w: float | None


def evaluate_alerts(snapshots: List[InverterSnapshot], now: datetime) -> List[Alert]:
    """
    Extremely simple v1 logic:

    - If Modbus read failed -> ALERT
    - If status is Fault / Shutdown -> ALERT
    - If PAC=0 and status is not Sleeping and it's daytime-ish -> ALERT

    No Astral or exact daylight logic yet; we can extend later.
    """
    alerts: list[Alert] = []

    for s in snapshots:
        if s.error:
            alerts.append(
                Alert(
                    inverter_name=s.name,
                    serial=s.serial,
                    message=f"{s.name} Modbus read failed: {s.error}",
                    status=s.status,
                    pac_w=s.pac_w,
                )
            )
            continue

        status_txt = STATUS_TEXT.get(s.status, f"Status={s.status}")
        pac = s.pac_w or 0.0

        # Fault or Shutdown
        if s.status in (6, 7):
            alerts.append(
                Alert(
                    inverter_name=s.name,
                    serial=s.serial,
                    message=f"{s.name} in {status_txt}. (PAC={pac:.0f}W, status={s.status})",
                    status=s.status,
                    pac_w=s.pac_w,
                )
            )
            continue

        # Extremely naive "daytime" guess: 06:00–20:00
        hour = now.hour
        is_dayish = 6 <= hour <= 20

        if is_dayish and pac <= 0 and s.status not in (1, 2, 6, 7):  # not Off/Sleeping/Shutdown/Fault
            alerts.append(
                Alert(
                    inverter_name=s.name,
                    serial=s.serial,
                    message=f"{s.name} PAC=0W during daytime. (status={s.status})",
                    status=s.status,
                    pac_w=s.pac_w,
                )
            )

    return alerts
