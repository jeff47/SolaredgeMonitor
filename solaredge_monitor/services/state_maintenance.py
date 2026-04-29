from __future__ import annotations

import datetime as dt


def _cutoff(days: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=days)).isoformat()


def prune(
    state,
    snapshot_days: int,
    summary_days: int,
    *,
    incident_days: int | None = None,
    incident_event_days: int | None = None,
    health_counter_days: int | None = None,
    vacuum: bool = True,
) -> None:
    if not getattr(state, "_persist", False) or not getattr(state, "_conn", None):
        return
    snap_cutoff = _cutoff(snapshot_days)
    summary_cutoff = _cutoff(summary_days)
    incident_cutoff = _cutoff(incident_days if incident_days is not None else summary_days)
    incident_event_cutoff = _cutoff(
        incident_event_days if incident_event_days is not None else summary_days
    )
    health_counter_cutoff = _cutoff(
        health_counter_days if health_counter_days is not None else summary_days
    )
    conn = state._conn
    with conn:
        conn.execute(
            "DELETE FROM inverter_snapshots WHERE run_timestamp < ?",
            (snap_cutoff,),
        )
        conn.execute(
            "DELETE FROM site_summaries WHERE recorded_at < ?",
            (summary_cutoff,),
        )
        conn.execute(
            "DELETE FROM incidents WHERE status = 'closed' AND COALESCE(recovered_at, last_seen) < ?",
            (incident_cutoff,),
        )
        conn.execute(
            "DELETE FROM incident_events WHERE event_ts < ?",
            (incident_event_cutoff,),
        )
        conn.execute(
            "DELETE FROM health_counters WHERE COALESCE(updated_at, '1970-01-01T00:00:00+00:00') < ?",
            (health_counter_cutoff,),
        )
    if vacuum:
        conn.execute("VACUUM")
