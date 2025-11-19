# solaredge_monitor/services/simulation_api_client.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from solaredge_monitor.models.optimizer import OptimizerStatus
from solaredge_monitor.services.se_api_client import CloudInverter


class SimulationAPIClient:
    """Provide SolarEdge-like API responses backed by config data."""

    def __init__(
        self,
        fault_type: str | None,
        cfg: Dict[str, Any] | None,
        log,
        *,
        enabled: bool = True,
    ) -> None:
        self.fault = fault_type
        self.cfg_root: Dict[str, Any] = cfg or {}
        self.scenario_cfg: Dict[str, str] = (
            self.cfg_root.get(fault_type, {}) if fault_type else {}
        )
        self.log = log
        self._enabled = enabled

    # ----------------------------------------------------------
    @staticmethod
    def parse_kv_list(raw: Optional[str], numeric: bool = True) -> Dict[str, float | str]:
        if not raw:
            return {}
        out: Dict[str, float | str] = {}
        for item in raw.split(","):
            if ":" not in item:
                continue
            key, value = item.split(":", 1)
            key = key.strip()
            if not key:
                continue
            if numeric:
                try:
                    out[key] = float(value.strip())
                except ValueError:
                    continue
            else:
                out[key] = value.strip()
        return out

    @staticmethod
    def parse_list(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _get_value(self, key: str) -> Optional[str]:
        if key in self.scenario_cfg:
            return self.scenario_cfg[key]
        value = self.cfg_root.get(key)
        if isinstance(value, str):
            return value
        return None

    def _get_map(self, key: str, numeric: bool = True) -> Dict[str, float | str]:
        raw = self._get_value(key)
        return self.parse_kv_list(raw, numeric=numeric)

    def _get_list(self, key: str) -> List[str]:
        raw = self._get_value(key)
        return self.parse_list(raw)

    # ----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self._enabled)

    # ----------------------------------------------------------
    def fetch_inverters(self) -> List[CloudInverter]:
        names = self._get_list("inverters")
        serial_map = self.parse_kv_list(self._get_value("inverter_serial"), numeric=False)
        status_map = self.parse_kv_list(self._get_value("inverter_status"), numeric=False)
        model_map = self.parse_kv_list(self._get_value("inverter_model"), numeric=False)
        optimizer_map = self._get_map("inverter_optimizers", numeric=True)

        inventory: List[CloudInverter] = []
        for name in names:
            serial = serial_map.get(name, name)
            optimizer_entry = optimizer_map.get(name)
            connected = int(optimizer_entry) if optimizer_entry is not None else None
            inventory.append(
                CloudInverter(
                    serial=str(serial).upper(),
                    name=name,
                    status=status_map.get(name),
                    model=model_map.get(name, "SIM"),
                    connected_optimizers=connected,
                    raw={"source": "simulation"},
                )
            )
        return inventory

    # ----------------------------------------------------------
    def get_optimizer_counts(self, inventory: Optional[List[CloudInverter]] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        source = inventory if inventory is not None else self.fetch_inverters()
        for inv in source:
            if inv.connected_optimizers is None:
                continue
            counts[inv.serial.upper()] = inv.connected_optimizers
        return counts

    # ----------------------------------------------------------
    def get_daily_production(self, day) -> Optional[float]:  # pragma: no cover - day unused
        per_inv = self._get_map("inverter_daily_wh", numeric=True)
        if not per_inv:
            return None
        return sum(float(value) for value in per_inv.values())

    # ----------------------------------------------------------
    def get_inverter_daily_energy(self, serial: str, day) -> Optional[float]:
        per_inv = self._get_map("inverter_daily_wh", numeric=True)
        if not per_inv:
            return None
        serial_norm = serial.upper() if serial else None
        if not serial_norm:
            return None
        if serial_norm in per_inv:
            return float(per_inv[serial_norm])
        for key, value in per_inv.items():
            if key.upper() == serial_norm:
                return float(value)
        return None

    # ----------------------------------------------------------
    def get_optimizer_statuses(self) -> List[OptimizerStatus]:
        now = datetime.now().isoformat()
        opt_counts = self._get_map("inverter_optimizers", numeric=True)
        statuses: List[OptimizerStatus] = []
        for inv, count in opt_counts.items():
            try:
                num = int(count)
            except (TypeError, ValueError):
                continue
            for idx in range(num):
                statuses.append(
                    OptimizerStatus(
                        optimizer_id=f"{inv}-OPT-{idx+1}",
                        inverter_serial=str(inv).upper(),
                        last_seen=now,
                        status="active",
                    )
                )
        return statuses
