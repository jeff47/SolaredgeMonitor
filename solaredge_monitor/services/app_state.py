# solaredge_monitor/services/app_state.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


def _day_str(day) -> str:
    return day if isinstance(day, str) else day.isoformat()


class AppState:
    """Shared persistent state for serial mappings and daily energy baselines."""

    def __init__(self, path: Optional[Path] = None):
        default_path = Path.home() / ".solaredge_monitor_state.json"
        self.path = Path(path or default_path)
        self.data = self._load()

    def _load(self) -> Dict:
        if not self.path.exists():
            return {}
        try:
            with self.path.open() as fh:
                obj = json.load(fh)
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
        return {}

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=2))
        except Exception:
            pass

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    # Serial mappings -----------------------------------------------------
    def update_inverter_serial(self, name: str, serial: str) -> None:
        if not name or not serial:
            return
        serials = self.data.setdefault("inverter_serials", {})
        serials[name] = serial.upper()
        self.save()

    def get_inverter_serial(self, name: str) -> Optional[str]:
        serials = self.data.get("inverter_serials", {})
        serial = serials.get(name)
        return serial.upper() if serial else None

    # Latest totals (for current day fallback) ---------------------------
    def update_latest_total(self, serial: str, day, total_wh: float) -> None:
        if serial is None or total_wh is None:
            return
        serial = serial.upper()
        totals = self.data.setdefault("latest_totals", {})
        totals[serial] = {"day": _day_str(day), "total_wh": total_wh}
        self.save()

    def get_latest_total(self, serial: str, day) -> Optional[float]:
        if not serial:
            return None
        entry = self.data.get("latest_totals", {}).get(serial.upper())
        if entry and entry.get("day") == _day_str(day):
            return entry.get("total_wh")
        return None

    # Summary baselines ---------------------------------------------------
    def get_summary_baseline(self, serial: str) -> tuple[Optional[str], Optional[float]]:
        if not serial:
            return None, None
        entry = self.data.get("summary_totals", {}).get(serial.upper())
        if not entry:
            return None, None
        return entry.get("day"), entry.get("total_wh")

    def set_summary_baseline(self, serial: str, day, total_wh: float) -> None:
        if serial is None or total_wh is None:
            return
        totals = self.data.setdefault("summary_totals", {})
        totals[serial.upper()] = {"day": _day_str(day), "total_wh": total_wh}
        self.save()
