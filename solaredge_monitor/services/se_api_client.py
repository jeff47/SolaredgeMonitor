from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import requests

from solaredge_monitor.config import SolarEdgeAPIConfig


@dataclass
class CloudInverter:
    serial: str
    name: str
    status: str | None
    model: str | None
    connected_optimizers: int | None
    raw: Dict[str, Any]


class SolarEdgeAPIClient:
    """Minimal SolarEdge Monitoring API wrapper with resilient parsing."""

    API_BASE_DEFAULT = "https://monitoringapi.solaredge.com"

    def __init__(self, cfg: SolarEdgeAPIConfig, log, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.log = log
        self.session = session or requests.Session()
        self.base_url = (cfg.base_url or self.API_BASE_DEFAULT).rstrip("/")

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.api_key and self.cfg.site_id)

    # ------------------------------------------------------------------
    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _normalize_serial(self, value: Any) -> str | None:
        if not value:
            return None
        serial = str(value).strip().upper()
        return serial or None

    def _serial_variants(self, value: Any) -> List[str]:
        """Return normalized serial plus a hyphen-stripped variant (if present)."""
        serial = self._normalize_serial(value)
        if not serial:
            return []

        variants = [serial]
        if "-" in serial:
            base_serial = serial.split("-", 1)[0]
            if base_serial and base_serial not in variants:
                variants.append(base_serial)
        return variants

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        if not self.enabled:
            self.log.debug("SolarEdge API disabled; skipping %s", path)
            return None

        query = dict(params or {})
        query["api_key"] = self.cfg.api_key
        url = self._build_url(path)

        try:
            resp = self.session.get(url, params=query, timeout=self.cfg.timeout)
        except Exception as exc:  # pragma: no cover - network errors
            self.log.warning("SolarEdge API request failed for %s: %s", path, exc)
            return None

        if resp.status_code != 200:
            self.log.warning("SolarEdge API %s returned HTTP %s", path, resp.status_code)
            return None

        try:
            data = resp.json()
        except ValueError:
            self.log.warning("SolarEdge API %s returned non-JSON payload", path)
            return None

        if isinstance(data, dict) and data.get("errors"):
            self.log.warning("SolarEdge API %s reported errors: %s", path, data["errors"])
            return None

        if isinstance(data, str):
            self.log.warning("SolarEdge API %s response was unexpected string payload", path)
            return None

        return data

    # ------------------------------------------------------------------
    def fetch_inverters(self) -> List[CloudInverter]:
        payload = self._get(f"/site/{self.cfg.site_id}/inventory")
        if not isinstance(payload, dict):
            return []

        inv_root = payload.get("inventory") or payload.get("Inventory") or {}
        inverter_list = (
            inv_root.get("inverters")
            or inv_root.get("Inverters")
            or inv_root.get("inverter")
            or []
        )

        cloud_inverters: List[CloudInverter] = []
        for entry in inverter_list:
            if not isinstance(entry, dict):
                continue
            serial = self._normalize_serial(
                entry.get("serialNumber")
                or entry.get("serial")
                or entry.get("SN")
                or entry.get("DEVICE_SN")
            )
            if not serial:
                continue

            name = entry.get("name") or serial
            status_field = entry.get("status")
            if isinstance(status_field, dict):
                status_text = (
                    status_field.get("status")
                    or status_field.get("statusDescription")
                )
            else:
                status_text = status_field

            connected = None
            if isinstance(entry.get("optimizers"), list):
                connected = len(entry["optimizers"])
            elif entry.get("connectedOptimizers") is not None:
                try:
                    connected = int(entry["connectedOptimizers"])
                except (ValueError, TypeError):
                    connected = None

            model = entry.get("model") or entry.get("modelNumber")

            cloud_inverters.append(
                CloudInverter(
                    serial=serial,
                    name=name,
                    status=status_text,
                    model=model,
                    connected_optimizers=connected,
                    raw=entry,
                )
            )

        return cloud_inverters

    # ------------------------------------------------------------------
    def get_optimizer_counts(self, inventory: Optional[List[CloudInverter]] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        inv_list = inventory if inventory is not None else self.fetch_inverters()
        for inv in inv_list:
            if inv.connected_optimizers is not None:
                for serial in self._serial_variants(inv.serial):
                    counts.setdefault(serial, inv.connected_optimizers)
        return counts

    # ------------------------------------------------------------------
    def check_optimizer_expectations(
        self,
        expectations: Dict[str, int],
        inventory: Optional[List[CloudInverter]] = None,
    ) -> List[str]:
        if not expectations or not self.enabled:
            return []

        inv_list = inventory if inventory is not None else self.fetch_inverters()
        counts = self.get_optimizer_counts(inv_list)
        alerts: List[str] = []

        for name, expected in expectations.items():
            serial = None
            for inv in inv_list:
                if inv.name == name:
                    serial = self._normalize_serial(inv.serial) or inv.serial
                    break
            if not serial:
                alerts.append(
                    f"[{name}] Missing optimizer data in SolarEdge inventory"
                )
                continue
            actual = counts.get(serial)
            if actual is None:
                alerts.append(
                    f"[{name}] Missing optimizer count data from SolarEdge cloud"
                )
            elif actual != expected:
                alerts.append(
                    f"[{name}] Optimizer count mismatch (expected {expected}, got {actual})"
                )
        return alerts

    # ------------------------------------------------------------------
    def get_daily_production(self, day: date) -> Optional[float]:
        """Return total site production (kWh) for the provided date."""
        data = self._get(
            f"/site/{self.cfg.site_id}/energy",
            params={
                "timeUnit": "DAY",
                "startDate": day.isoformat(),
                "endDate": day.isoformat(),
            },
        )

        if not isinstance(data, dict):
            return None

        energy = data.get("energy") or {}
        values = energy.get("values") or []
        if not values:
            return None

        first = values[0] or {}
        value = first.get("value")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    def get_inverter_daily_energy(self, serial: str, day: date) -> Optional[float]:
        if not self.enabled:
            return None

        serial_norm = self._normalize_serial(serial) or serial
        path = f"/site/{self.cfg.site_id}/equipment/{serial_norm}/data"
        params = {
            "startTime": f"{day.isoformat()} 00:00:00",
            "endTime": f"{day.isoformat()} 23:59:59",
        }
        data = self._get(path, params=params)
        if not isinstance(data, dict):
            return None

        payload = data.get("data") or {}
        values = payload.get("values") or []
        total = 0.0
        found = False

        for entry in values:
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            try:
                total += float(value)
                found = True
            except (TypeError, ValueError):
                continue

        return total if found else None
