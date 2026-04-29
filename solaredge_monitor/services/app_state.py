# solaredge_monitor/services/app_state.py

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
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
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._tx_depth = 0
            self._init_schema()
        else:
            self.path = None
            self._conn = None
            self._memory: Dict[str, Dict] = {
                "kv": {},
                "inverter_serials": {},
                "latest_totals": {},
                "summary_totals": {},
                "health_counters": {},
                "open_incidents": {},
            }
            self._tx_depth = 0

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
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_key TEXT NOT NULL,
                inverter_name TEXT NOT NULL,
                serial TEXT,
                fault_code TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_alerted TEXT,
                alert_count INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                recovered_at TEXT,
                recovery_message TEXT
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_incidents_open
            ON incidents(incident_key, status)
            WHERE status='open'
            """,
            """
            CREATE TABLE IF NOT EXISTS incident_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_ts TEXT NOT NULL,
                message TEXT,
                payload_json TEXT,
                FOREIGN KEY(incident_id) REFERENCES incidents(id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_incident_events_incident_ts
            ON incident_events(incident_id, event_ts)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_incidents_status_fault_last_seen
            ON incidents(status, fault_code, last_seen)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_incidents_inverter_status
            ON incidents(inverter_name, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_incident_events_type_ts
            ON incident_events(event_type, event_ts)
            """,
            """
            CREATE TABLE IF NOT EXISTS health_counters (
                inverter_name TEXT PRIMARY KEY,
                failure_streak INTEGER NOT NULL DEFAULT 0,
                recovery_streak INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
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

    @contextmanager
    def transaction(self):
        if not self._persist or not self._conn:
            yield
            return
        outer = self._tx_depth == 0
        if outer:
            self._conn.execute("BEGIN")
        self._tx_depth += 1
        try:
            yield
            self._tx_depth -= 1
            if outer:
                self._conn.commit()
        except Exception:
            self._tx_depth -= 1
            if outer:
                self._conn.rollback()
            raise

    def _maybe_commit(self) -> None:
        if self._persist and self._conn and self._tx_depth == 0:
            self._conn.commit()

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

    def has_site_summary(self, day) -> bool:
        day_key = _day_str(day)
        if not self._persist:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM site_summaries WHERE day = ? LIMIT 1",
            (day_key,),
        ).fetchone()
        return row is not None

    def get_health_counters(self) -> dict[str, tuple[int, int]]:
        if not self._persist:
            counters = self._memory.get("health_counters", {})
            out: dict[str, tuple[int, int]] = {}
            for name, values in counters.items():
                if not isinstance(values, dict):
                    continue
                out[str(name)] = (
                    int(values.get("failure_streak", 0) or 0),
                    int(values.get("recovery_streak", 0) or 0),
                )
            return out
        cur = self._conn.execute(
            "SELECT inverter_name, failure_streak, recovery_streak FROM health_counters"
        )
        out: dict[str, tuple[int, int]] = {}
        for row in cur.fetchall():
            out[str(row["inverter_name"])] = (
                int(row["failure_streak"] or 0),
                int(row["recovery_streak"] or 0),
            )
        return out

    def upsert_health_counters(
        self,
        counters: Mapping[str, tuple[int, int]],
        updated_at: Optional[str] = None,
    ) -> None:
        if not self._persist:
            mem = self._memory.setdefault("health_counters", {})
            for name, values in counters.items():
                failure_streak, recovery_streak = values
                mem[str(name)] = {
                    "failure_streak": int(failure_streak),
                    "recovery_streak": int(recovery_streak),
                    "updated_at": updated_at,
                }
            return
        for name, values in counters.items():
            failure_streak, recovery_streak = values
            self._conn.execute(
                """
                INSERT INTO health_counters(inverter_name, failure_streak, recovery_streak, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(inverter_name) DO UPDATE SET
                    failure_streak=excluded.failure_streak,
                    recovery_streak=excluded.recovery_streak,
                    updated_at=excluded.updated_at
                """,
                (
                    str(name),
                    int(failure_streak),
                    int(recovery_streak),
                    updated_at,
                ),
            )
        self._maybe_commit()

    def get_open_incidents(self) -> dict[str, dict]:
        if not self._persist:
            raw = self._memory.get("open_incidents", {})
            return {
                str(k): dict(v)
                for k, v in raw.items()
                if isinstance(v, dict)
            }
        cur = self._conn.execute(
            """
            SELECT incident_key, serial, fault_code, fingerprint, message, status,
                   first_seen, last_seen, last_alerted, alert_count, source
            FROM incidents
            WHERE status='open'
            """
        )
        incidents: dict[str, dict] = {}
        for row in cur.fetchall():
            key = str(row["incident_key"])
            incidents[key] = {
                "serial": row["serial"],
                "fault_code": row["fault_code"],
                "fingerprint": row["fingerprint"],
                "message": row["message"],
                "status": row["status"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "last_alerted": row["last_alerted"],
                "alert_count": int(row["alert_count"] or 0),
                "source": row["source"],
            }
        return incidents

    def upsert_open_incident(
        self,
        *,
        incident_key: str,
        inverter_name: str,
        serial: str,
        fault_code: str,
        fingerprint: str,
        message: str,
        first_seen: str,
        last_seen: str,
        last_alerted: Optional[str],
        alert_count: int,
        source: str,
        event_type: str,
        event_ts: str,
        payload: Optional[dict] = None,
    ) -> None:
        if not self._persist:
            mem = self._memory.setdefault("open_incidents", {})
            mem[incident_key] = {
                "fingerprint": fingerprint,
                "serial": serial,
                "fault_code": fault_code,
                "message": message,
                "status": "open",
                "first_seen": first_seen,
                "last_seen": last_seen,
                "last_alerted": last_alerted,
                "alert_count": int(alert_count),
                "source": source,
            }
            return
        row = self._conn.execute(
            "SELECT id FROM incidents WHERE incident_key = ? AND status = 'open'",
            (incident_key,),
        ).fetchone()
        if row:
            incident_id = int(row["id"])
            self._conn.execute(
                """
                UPDATE incidents
                SET inverter_name=?,
                    serial=?,
                    fault_code=?,
                    fingerprint=?,
                    message=?,
                    last_seen=?,
                    last_alerted=?,
                    alert_count=?,
                    source=?
                WHERE id=?
                """,
                (
                    inverter_name,
                    serial,
                    fault_code,
                    fingerprint,
                    message,
                    last_seen,
                    last_alerted,
                    alert_count,
                    source,
                    incident_id,
                ),
            )
        else:
            cur = self._conn.execute(
                """
                INSERT INTO incidents(
                    incident_key, inverter_name, serial, fault_code, fingerprint,
                    status, message, first_seen, last_seen, last_alerted,
                    alert_count, source
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_key,
                    inverter_name,
                    serial,
                    fault_code,
                    fingerprint,
                    message,
                    first_seen,
                    last_seen,
                    last_alerted,
                    int(alert_count),
                    source,
                ),
            )
            incident_id = int(cur.lastrowid)
        self._conn.execute(
            """
            INSERT INTO incident_events(incident_id, event_type, event_ts, message, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                event_type,
                event_ts,
                message,
                json.dumps(payload) if payload is not None else None,
            ),
        )
        self._maybe_commit()

    def close_incident(
        self,
        *,
        incident_key: str,
        resolved_at: str,
        recovery_message: str,
        event_type: str = "recovered",
        payload: Optional[dict] = None,
    ) -> None:
        if not self._persist:
            mem = self._memory.setdefault("open_incidents", {})
            mem.pop(incident_key, None)
            return
        row = self._conn.execute(
            "SELECT id FROM incidents WHERE incident_key = ? AND status = 'open'",
            (incident_key,),
        ).fetchone()
        if not row:
            return
        incident_id = int(row["id"])
        self._conn.execute(
            """
            UPDATE incidents
            SET status='closed', recovered_at=?, recovery_message=?, last_seen=?
            WHERE id=?
            """,
            (resolved_at, recovery_message, resolved_at, incident_id),
        )
        self._conn.execute(
            """
            INSERT INTO incident_events(incident_id, event_type, event_ts, message, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                event_type,
                resolved_at,
                recovery_message,
                json.dumps(payload) if payload is not None else None,
            ),
        )
        self._maybe_commit()

    # ------------------------------------------------------------------
    def __del__(self):
        try:
            self.flush()
            if self._conn:
                self._conn.close()
        except Exception:
            pass
