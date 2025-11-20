# solaredge_monitor/services/app_state.py

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from solaredge_monitor.models.inverter import InverterSnapshot
    from solaredge_monitor.models.system_health import SystemHealth
    from solaredge_monitor.services.se_api_client import CloudInverter


def _day_str(day) -> str:
    if hasattr(day, "isoformat"):
        return day.isoformat()
    return str(day)


class AppState:
    """SQLite-backed state store plus historical run logging."""

    def __init__(self, path: Optional[Union[Path, str]] = None, *, persist: bool = True):
        default_path = Path.home() / ".solaredge_monitor_state.db"
        self._persist = persist
        self._log = logging.getLogger("solaredge.state")
        if self._persist:
            resolved = Path(path) if path else default_path
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self.path: Optional[Path] = resolved
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_schema()
        else:
            self.path = None
            self._conn = None
            self._memory: Dict[str, Dict] = {
                "kv": {},
                "inverter_serials": {},
                "latest_totals": {},
                "summary_totals": {},
            }

    # ------------------------------------------------------------------
    def _init_schema(self) -> None:
        stmts = [
            """
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS inverter_serials (
                name TEXT PRIMARY KEY,
                serial TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS latest_totals (
                serial TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                total_wh REAL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS summary_totals (
                serial TEXT PRIMARY KEY,
                day TEXT NOT NULL,
                total_wh REAL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS inverter_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT NOT NULL,
                inverter_name TEXT NOT NULL,
                serial TEXT,
                status INTEGER,
                pac_w REAL,
                vdc_v REAL,
                idc_a REAL,
                total_wh REAL,
                optimizer_count INTEGER,
                daylight_phase TEXT,
                healthy INTEGER NOT NULL,
                health_reason TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS site_summaries (
                day TEXT PRIMARY KEY,
                recorded_at TEXT NOT NULL,
                site_wh_modbus REAL,
                site_wh_api REAL
            )
            """,
        ]
        for stmt in stmts:
            self._conn.execute(stmt)
        self._conn.commit()

    # ------------------------------------------------------------------
    def flush(self) -> None:
        if self._persist and self._conn:
            self._conn.commit()

    def save(self) -> None:
        self.flush()

    # ------------------------------------------------------------------
    def get(self, key: str, default=None):
        if not self._persist:
            return self._memory["kv"].get(key, default)
        cur = self._conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value) -> None:
        if not self._persist:
            self._memory["kv"][key] = value
            return
        payload = json.dumps(value)
        self._conn.execute(
            """
            INSERT INTO kv_store(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, payload),
        )
        self._conn.commit()

    # Serial mappings -------------------------------------------------
    def update_inverter_serial(self, name: str, serial: str) -> None:
        if not name or not serial:
            return
        serial_fmt = serial.upper()
        if not self._persist:
            self._memory["inverter_serials"][name] = serial_fmt
            return
        self._conn.execute(
            """
            INSERT INTO inverter_serials(name, serial)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET serial=excluded.serial
            """,
            (name, serial_fmt),
        )
        self._conn.commit()

    def get_inverter_serial(self, name: str) -> Optional[str]:
        if not name:
            return None
        if not self._persist:
            serial = self._memory["inverter_serials"].get(name)
            return serial.upper() if serial else None
        cur = self._conn.execute("SELECT serial FROM inverter_serials WHERE name = ?", (name,))
        row = cur.fetchone()
        return row["serial"].upper() if row else None

    # Latest totals ---------------------------------------------------
    def update_latest_total(self, serial: str, day, total_wh: float) -> None:
        if not serial or total_wh is None:
            return
        serial_fmt = serial.upper()
        day_str = _day_str(day)
        if not self._persist:
            self._memory["latest_totals"][serial_fmt] = {"day": day_str, "total_wh": total_wh}
            return
        self._conn.execute(
            """
            INSERT INTO latest_totals(serial, day, total_wh)
            VALUES (?, ?, ?)
            ON CONFLICT(serial) DO UPDATE SET day=excluded.day, total_wh=excluded.total_wh
            """,
            (serial_fmt, day_str, total_wh),
        )
        self._conn.commit()

    def get_latest_total(self, serial: str, day) -> Optional[float]:
        if not serial:
            return None
        serial_fmt = serial.upper()
        day_str = _day_str(day)
        if not self._persist:
            entry = self._memory["latest_totals"].get(serial_fmt)
            if entry and entry.get("day") == day_str:
                return entry.get("total_wh")
            return None
        cur = self._conn.execute(
            "SELECT day, total_wh FROM latest_totals WHERE serial = ?",
            (serial_fmt,),
        )
        row = cur.fetchone()
        if row and row["day"] == day_str:
            return row["total_wh"]
        return None

    # Summary baselines ----------------------------------------------
    def get_summary_baseline(self, serial: str) -> tuple[Optional[str], Optional[float]]:
        if not serial:
            return None, None
        serial_fmt = serial.upper()
        if not self._persist:
            entry = self._memory["summary_totals"].get(serial_fmt)
            if not entry:
                return None, None
            return entry.get("day"), entry.get("total_wh")
        cur = self._conn.execute(
            "SELECT day, total_wh FROM summary_totals WHERE serial = ?",
            (serial_fmt,),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        return row["day"], row["total_wh"]

    def set_summary_baseline(self, serial: str, day, total_wh: float) -> None:
        if serial is None or total_wh is None:
            return
        serial_fmt = serial.upper()
        day_str = _day_str(day)
        if not self._persist:
            self._memory["summary_totals"][serial_fmt] = {"day": day_str, "total_wh": total_wh}
            return
        self._conn.execute(
            """
            INSERT INTO summary_totals(serial, day, total_wh)
            VALUES (?, ?, ?)
            ON CONFLICT(serial) DO UPDATE SET day=excluded.day, total_wh=excluded.total_wh
            """,
            (serial_fmt, day_str, total_wh),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    def log_health_run(
        self,
        run_timestamp: datetime,
        daylight_phase: str,
        snapshots: Mapping[str, Optional["InverterSnapshot"]],
        health: Optional["SystemHealth"],
        cloud_by_serial: Mapping[str, "CloudInverter"],
        optimizer_counts: Optional[Mapping[str, int]] = None,
    ) -> None:
        if not self._persist or not snapshots:
            return
        run_ts = run_timestamp.isoformat()
        per_inverter = health.per_inverter if health else {}
        with self._conn:
            for name, snapshot in snapshots.items():
                inv_health = per_inverter.get(name)
                healthy = inv_health.inverter_ok if inv_health else False
                reason = inv_health.reason if inv_health else None
                serial = snapshot.serial if snapshot else None
                status = snapshot.status if snapshot else None
                pac_w = snapshot.pac_w if snapshot else None
                vdc_v = snapshot.vdc_v if snapshot else None
                idc_a = snapshot.idc_a if snapshot else None
                total_wh = snapshot.total_wh if snapshot else None
                cloud = None
                if serial:
                    key = serial.upper()
                    cloud = cloud_by_serial.get(serial) or cloud_by_serial.get(key)
                optimizer_count = None
                if optimizer_counts and serial:
                    optimizer_count = optimizer_counts.get(serial)
                if optimizer_count is None and optimizer_counts and serial:
                    optimizer_count = optimizer_counts.get(serial.upper())
                if optimizer_count is None and cloud is not None:
                    optimizer_count = getattr(cloud, "connected_optimizers", None)
                self._conn.execute(
                    """
                    INSERT INTO inverter_snapshots (
                        run_timestamp,
                        inverter_name,
                        serial,
                        status,
                        pac_w,
                        vdc_v,
                        idc_a,
                        total_wh,
                        optimizer_count,
                        daylight_phase,
                        healthy,
                        health_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_ts,
                        name,
                        serial,
                        status,
                        pac_w,
                        vdc_v,
                        idc_a,
                        total_wh,
                        optimizer_count,
                        daylight_phase,
                        1 if healthy else 0,
                        reason,
                    ),
                )

    def record_site_summary(self, day, site_wh_modbus: Optional[float], site_wh_api: Optional[float]) -> None:
        if not self._persist:
            return
        day_key = _day_str(day)
        recorded_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO site_summaries(day, recorded_at, site_wh_modbus, site_wh_api)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                recorded_at=excluded.recorded_at,
                site_wh_modbus=excluded.site_wh_modbus,
                site_wh_api=excluded.site_wh_api
            """,
            (day_key, recorded_at, site_wh_modbus, site_wh_api),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    def __del__(self):
        try:
            self.flush()
            if self._conn:
                self._conn.close()
        except Exception:
            pass
