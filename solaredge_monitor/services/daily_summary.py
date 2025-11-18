from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, Optional

from solaredge_monitor.config import InverterConfig
from solaredge_monitor.models.daylight import DaylightInfo
from solaredge_monitor.services.se_api_client import SolarEdgeAPIClient, CloudInverter
from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.models.inverter import InverterSnapshot


@dataclass
class SummaryResult:
    day: date
    site_wh_api: Optional[float]
    site_wh_modbus: Optional[float]
    per_inverter_wh: list[tuple[str, Optional[float]]]


class DailySummaryService:
    def __init__(
        self,
        inverter_cfgs: Iterable[InverterConfig],
        api_client: SolarEdgeAPIClient,
        log,
        state: Optional[AppState] = None,
    ):
        self.inverters = list(inverter_cfgs)
        self.api = api_client
        self.log = log
        self.state = state or AppState()

    # ------------------------------------------------------------------
    def _has_run(self, day: date) -> bool:
        return self.state.get("last_summary_date") == day.isoformat()

    def mark_ran(self, day: date) -> None:
        self.state.set("last_summary_date", day.isoformat())

    # ------------------------------------------------------------------
    def should_run(self, day: date, daylight: DaylightInfo) -> bool:
        if not daylight.production_day_over:
            return False
        return not self._has_run(day)

    # ------------------------------------------------------------------
    def run(
        self,
        day: date,
        inventory: Optional[list[CloudInverter]] = None,
        modbus_snapshots: Optional[Dict[str, InverterSnapshot]] = None,
    ) -> Optional[SummaryResult]:
        day_str = day.isoformat()

        if self.api.enabled:
            inventory = inventory or self.api.fetch_inverters()
            site_wh_api = self.api.get_daily_production(day)
        else:
            inventory = inventory or []
            site_wh_api = None

        per_inverter = []
        modbus_map = modbus_snapshots or {}
        modbus_total = 0.0
        modbus_values_present = False

        for inv_cfg in self.inverters:
            name = inv_cfg.name
            serial = self._resolve_serial(inv_cfg, inventory) or self.state.get_inverter_serial(name)

            snapshot = modbus_map.get(name)
            current_total = None
            if snapshot and snapshot.total_wh is not None:
                current_total = snapshot.total_wh
                serial = (snapshot.serial or serial)
            elif serial:
                current_total = self.state.get_latest_total(serial, day)

            if serial:
                self.state.update_inverter_serial(name, serial)
            serial_norm = serial.upper() if serial else None

            api_energy = (
                self.api.get_inverter_daily_energy(serial, day)
                if (self.api.enabled and serial)
                else None
            )

            prev_day, prev_total = self.state.get_summary_baseline(serial_norm) if serial_norm else (None, None)
            energy = None
            energy_source = None
            if (
                current_total is not None
                and prev_total is not None
                and prev_day != day_str
            ):
                delta = current_total - prev_total
                if delta >= 0:
                    energy = delta
                    energy_source = "modbus"
            elif api_energy is not None:
                energy = api_energy
                energy_source = "api"

            per_inverter.append((name, energy))
            if energy is not None and energy_source == "modbus":
                modbus_total += energy
                modbus_values_present = True

            if serial_norm and current_total is not None:
                self.state.update_latest_total(serial_norm, day, current_total)
                self.state.set_summary_baseline(serial_norm, day, current_total)

        site_wh_modbus = modbus_total if modbus_values_present else None
        summary = SummaryResult(
            day=day,
            site_wh_api=site_wh_api,
            site_wh_modbus=site_wh_modbus,
            per_inverter_wh=per_inverter,
        )

        self.mark_ran(day)
        return summary

    # ------------------------------------------------------------------
    def _resolve_serial(self, inv_cfg: InverterConfig, inventory: list[CloudInverter]) -> Optional[str]:
        for cloud in inventory:
            if cloud.name == inv_cfg.name:
                if cloud.serial:
                    return cloud.serial.upper()
        return self.state.get_inverter_serial(inv_cfg.name)

    # ------------------------------------------------------------------
    def format_summary(self, summary: SummaryResult) -> str:
        lines = [f"Daily production for {summary.day.isoformat()}:"]

        if summary.site_wh_modbus is not None:
            lines.append(f"Site total (Modbus): {summary.site_wh_modbus / 1000.0:.2f} kWh")
        else:
            lines.append("Site total (Modbus): unavailable")

        if summary.site_wh_api is not None:
            lines.append(f"Site total (API): {summary.site_wh_api / 1000.0:.2f} kWh")
        else:
            lines.append("Site total (API): unavailable")

        if summary.per_inverter_wh:
            lines.append("Per-inverter:")
            for name, energy in summary.per_inverter_wh:
                if energy is None:
                    lines.append(f"- {name}: unavailable")
                else:
                    lines.append(f"- {name}: {energy / 1000.0:.2f} kWh")

        return "\n".join(lines)
