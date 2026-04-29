from datetime import datetime, timedelta, timezone

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


def test_prune_incident_tables_and_counters(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(path=db_path)
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=40)).isoformat()
    recent_ts = now.isoformat()

    # closed old incident should be pruned
    state._conn.execute(
        """
        INSERT INTO incidents(
            incident_key, inverter_name, serial, fault_code, fingerprint, status, message,
            first_seen, last_seen, last_alerted, alert_count, source, recovered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "INV-OLD",
            "INV-OLD",
            "S1",
            "low_pac",
            "low_pac",
            "closed",
            "old",
            old_ts,
            old_ts,
            old_ts,
            1,
            "health",
            old_ts,
        ),
    )
    # open recent incident should remain
    state._conn.execute(
        """
        INSERT INTO incidents(
            incident_key, inverter_name, serial, fault_code, fingerprint, status, message,
            first_seen, last_seen, last_alerted, alert_count, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "INV-OPEN",
            "INV-OPEN",
            "S2",
            "low_vdc",
            "low_vdc",
            "open",
            "recent",
            recent_ts,
            recent_ts,
            recent_ts,
            1,
            "health",
        ),
    )
    old_incident_id = state._conn.execute(
        "SELECT id FROM incidents WHERE incident_key='INV-OLD'"
    ).fetchone()[0]
    open_incident_id = state._conn.execute(
        "SELECT id FROM incidents WHERE incident_key='INV-OPEN'"
    ).fetchone()[0]
    state._conn.execute(
        "INSERT INTO incident_events(incident_id, event_type, event_ts) VALUES (?, ?, ?)",
        (old_incident_id, "opened", old_ts),
    )
    state._conn.execute(
        "INSERT INTO incident_events(incident_id, event_type, event_ts) VALUES (?, ?, ?)",
        (open_incident_id, "opened", recent_ts),
    )
    state._conn.execute(
        "INSERT INTO health_counters(inverter_name, failure_streak, recovery_streak, updated_at) VALUES (?, ?, ?, ?)",
        ("INV-OLD", 3, 0, old_ts),
    )
    state._conn.execute(
        "INSERT INTO health_counters(inverter_name, failure_streak, recovery_streak, updated_at) VALUES (?, ?, ?, ?)",
        ("INV-OPEN", 1, 0, recent_ts),
    )
    state._conn.commit()

    state_maintenance.prune(
        state,
        snapshot_days=30,
        summary_days=30,
        incident_days=30,
        incident_event_days=30,
        health_counter_days=30,
        vacuum=False,
    )

    incidents = state._conn.execute(
        "SELECT incident_key, status FROM incidents ORDER BY incident_key"
    ).fetchall()
    assert [tuple(row) for row in incidents] == [("INV-OPEN", "open")]

    events = state._conn.execute(
        "SELECT event_ts FROM incident_events"
    ).fetchall()
    assert len(events) == 1
    assert tuple(events[0])[0] == recent_ts

    counters = state._conn.execute(
        "SELECT inverter_name FROM health_counters"
    ).fetchall()
    assert [tuple(row) for row in counters] == [("INV-OPEN",)]
