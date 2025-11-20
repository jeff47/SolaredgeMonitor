from datetime import datetime, date
from pathlib import Path

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
