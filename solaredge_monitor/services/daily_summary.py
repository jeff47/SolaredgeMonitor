from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from solaredge_monitor.config import InverterConfig
from solaredge_monitor.models.daylight import DaylightInfo
from solaredge_monitor.services.se_api_client import SolarEdgeAPIClient, CloudInverter


@dataclass
class SummaryResult:
    day: date
    site_wh: Optional[float]
    per_inverter_wh: list[tuple[str, Optional[float]]]


class DailySummaryService:
    DEFAULT_STATE_FILE = ".daily_summary_state.json"

    def __init__(
        self,
        inverter_cfgs: Iterable[InverterConfig],
        api_client: SolarEdgeAPIClient,
        log,
        state_path: Optional[Path] = None,
    ):
        self.inverters = list(inverter_cfgs)
        self.api = api_client
        self.log = log
        self.state_path = Path(state_path or self.DEFAULT_STATE_FILE)
        self.state = self._load_state()

    # ------------------------------------------------------------------
    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_state(self) -> None:
        try:
            self.state_path.write_text(json.dumps(self.state))
        except Exception as exc:
            self.log.debug(f"Failed to persist daily summary state: {exc}")

    # ------------------------------------------------------------------
    def _has_run(self, day: date) -> bool:
        return self.state.get("last_summary_date") == day.isoformat()

    def mark_ran(self, day: date) -> None:
        self.state["last_summary_date"] = day.isoformat()
        self._save_state()

    # ------------------------------------------------------------------
    def should_run(self, day: date, daylight: DaylightInfo) -> bool:
        if not self.api.enabled:
            return False
        if not daylight.production_day_over:
            return False
        return not self._has_run(day)

    # ------------------------------------------------------------------
    def run(self, day: date, inventory: Optional[list[CloudInverter]] = None) -> Optional[SummaryResult]:
        if not self.api.enabled:
            return None

        inventory = inventory or self.api.fetch_inverters()
        site_wh = self.api.get_daily_production(day)

        per_inverter = []
        for inv_cfg in self.inverters:
            serial = self._resolve_serial(inv_cfg, inventory)
            energy = self.api.get_inverter_daily_energy(serial, day) if serial else None
            per_inverter.append((inv_cfg.name, energy))

        summary = SummaryResult(day=day, site_wh=site_wh, per_inverter_wh=per_inverter)
        self.mark_ran(day)
        return summary

    # ------------------------------------------------------------------
    def _resolve_serial(self, inv_cfg: InverterConfig, inventory: list[CloudInverter]) -> Optional[str]:
        for cloud in inventory:
            if cloud.name == inv_cfg.name:
                return cloud.serial
        return None

    # ------------------------------------------------------------------
    def format_summary(self, summary: SummaryResult) -> str:
        lines = [f"Daily production for {summary.day.isoformat()}"]

        if summary.site_wh is not None:
            kwh = summary.site_wh / 1000.0
            lines.append(f"Site total: {kwh:.2f} kWh ({summary.site_wh:.0f} Wh)")
        else:
            lines.append("Site total: unavailable")

        if summary.per_inverter_wh:
            lines.append("Per-inverter:")
            for name, energy in summary.per_inverter_wh:
                if energy is None:
                    lines.append(f" - {name}: unavailable")
                else:
                    lines.append(f" - {name}: {energy / 1000.0:.2f} kWh ({energy:.0f} Wh)")

        return "\n".join(lines)
