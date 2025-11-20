from datetime import datetime, timedelta, timezone

import sqlite3

from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.services import state_maintenance


def _insert_snapshot(conn, ts, name="INV-A"):
    conn.execute(
        "INSERT INTO inverter_snapshots (run_timestamp, inverter_name, healthy) VALUES (?, ?, 1)",
        (ts, name),
    )


def test_prune_removes_rows(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(path=db_path)
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=40)).isoformat()
    recent_ts = now.isoformat()

    _insert_snapshot(state._conn, old_ts)
    _insert_snapshot(state._conn, recent_ts)
    state._conn.execute(
        "INSERT INTO site_summaries(day, recorded_at) VALUES (?, ?)",
        ("2024-01-01", old_ts),
    )
    state._conn.execute(
        "INSERT INTO site_summaries(day, recorded_at) VALUES (?, ?)",
        ("2024-02-01", recent_ts),
    )
    state._conn.commit()

    state_maintenance.prune(state, snapshot_days=30, summary_days=30, vacuum=False)

    rows = state._conn.execute("SELECT run_timestamp FROM inverter_snapshots").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == recent_ts
    summaries = state._conn.execute("SELECT recorded_at FROM site_summaries").fetchall()
    assert len(summaries) == 1
    assert summaries[0][0] == recent_ts
