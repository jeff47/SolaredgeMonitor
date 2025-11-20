from __future__ import annotations

import datetime as dt


def _cutoff(days: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=days)).isoformat()


def prune(state, snapshot_days: int, summary_days: int, *, vacuum: bool = True) -> None:
    if not getattr(state, "_persist", False) or not getattr(state, "_conn", None):
        return
    snap_cutoff = _cutoff(snapshot_days)
    summary_cutoff = _cutoff(summary_days)
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
    if vacuum:
        conn.execute("VACUUM")
