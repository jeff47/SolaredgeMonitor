from datetime import datetime, date

import sqlite3

from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.models.system_health import InverterHealth, SystemHealth
from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.services.se_api_client import CloudInverter


class DummySystemHealth(SystemHealth):
    def __init__(self, per_inverter):
        super().__init__(system_ok=all(inv.inverter_ok for inv in per_inverter.values()), per_inverter=per_inverter, reason=None)


def _snapshot(name: str) -> InverterSnapshot:
    return InverterSnapshot(
        name=name,
        serial=f"{name}-123",
        model="SIM",
        status=4,
        vendor_status=None,
        pac_w=500.0,
        vdc_v=400.0,
        idc_a=1.5,
        total_wh=120000.0,
        error=None,
        timestamp=datetime.now(),
    )


def test_app_state_logs_health_run(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(path=db_path)

    snap = _snapshot("INV-A")
    cloud = CloudInverter(
        serial=snap.serial,
        name=snap.name,
        status="Active",
        model="SIM",
        connected_optimizers=25,
        raw={},
    )
    per_inv = {snap.name: InverterHealth(name=snap.name, inverter_ok=True, reason=None, reading=snap)}
    health = DummySystemHealth(per_inv)

    state.log_health_run(
        run_timestamp=datetime(2024, 1, 1, 10, 0, 0),
        daylight_phase="DAY",
        snapshots={snap.name: snap},
        health=health,
        cloud_by_serial={cloud.serial: cloud},
        optimizer_counts={snap.serial: 30},
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT inverter_name, pac_w, optimizer_count, daylight_phase, healthy FROM inverter_snapshots"
    ).fetchone()
    assert row == (snap.name, snap.pac_w, 30, "DAY", 1)



def test_record_site_summary(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(path=db_path)

    state.record_site_summary(date(2024, 1, 1), site_wh_modbus=1000.0, site_wh_api=900.0)
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT site_wh_modbus, site_wh_api FROM site_summaries").fetchone()
    assert row == (1000.0, 900.0)


def test_incident_lifecycle_persistence(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(path=db_path)

    state.upsert_open_incident(
        incident_key="INV-A",
        inverter_name="INV-A",
        serial="SER123",
        fault_code="low_pac",
        fingerprint="low_pac",
        message="Producing but PAC low",
        first_seen="2026-04-28T19:20:00-04:00",
        last_seen="2026-04-28T19:20:00-04:00",
        last_alerted="2026-04-28T19:20:00-04:00",
        alert_count=1,
        source="health",
        event_type="opened",
        event_ts="2026-04-28T19:20:00-04:00",
        payload={"status": 4},
    )
    state.upsert_open_incident(
        incident_key="INV-A",
        inverter_name="INV-A",
        serial="SER123",
        fault_code="low_pac",
        fingerprint="low_pac",
        message="Producing but PAC still low",
        first_seen="2026-04-28T19:20:00-04:00",
        last_seen="2026-04-28T19:25:00-04:00",
        last_alerted="2026-04-28T19:25:00-04:00",
        alert_count=2,
        source="health",
        event_type="repeat_alert",
        event_ts="2026-04-28T19:25:00-04:00",
        payload={"status": 4},
    )
    state.close_incident(
        incident_key="INV-A",
        resolved_at="2026-04-28T19:40:00-04:00",
        recovery_message="Recovered after 0:20:00: Producing but PAC low",
    )

    conn = sqlite3.connect(db_path)
    incident = conn.execute(
        "SELECT status, alert_count, recovered_at FROM incidents WHERE incident_key='INV-A'"
    ).fetchone()
    assert incident == ("closed", 2, "2026-04-28T19:40:00-04:00")

    events = conn.execute(
        "SELECT event_type FROM incident_events ORDER BY id"
    ).fetchall()
    assert [row[0] for row in events] == ["opened", "repeat_alert", "recovered"]


def test_health_counters_persist_across_reopen(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(path=db_path)
    state.upsert_health_counters(
        {
            "INV-A": (2, 0),
            "INV-B": (0, 3),
        },
        updated_at="2026-04-29T08:00:00-04:00",
    )
    state.flush()

    reopened = AppState(path=db_path)
    counters = reopened.get_health_counters()
    assert counters["INV-A"] == (2, 0)
    assert counters["INV-B"] == (0, 3)
