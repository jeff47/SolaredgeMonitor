# SolarEdge Monitor

This project polls SolarEdge inverters over Modbus, combines the readings with SolarEdge cloud data, evaluates system health, and pushes notifications via Pushover/Healthchecks. The CLI also supports simulated runs for testing and a SQLite-backed state/retention layer.

## Features

- **Modbus health checks**: Reads configured inverters, evaluates per-inverter rules plus peer comparisons, and reports alerts.
- **SolarEdge API integration**: Pulls status/optimizer counts from the cloud when enabled, enriching alerts and summaries.
- **Daylight-aware polling**: A daylight policy decides whether to skip Modbus/cloud calls at night and when summaries should run.
- **Simulation mode**: Use `[simulation]` config sections or `simulate --scenario NAME` to test alert logic with synthetic data and timestamps.
- **SQLite history**: Per-run snapshots, optimizer counts, and site summaries are stored in `~/.solaredge_monitor_state.db` (or the path you specify).
- **Retention/maintenance**: Configurable pruning and a `maintain-db` CLI command keep the database from growing indefinitely.

## Configuration

Edit `solaredge_monitor.conf` to define your environment:

- `[daylight]`: Timezone plus optional coordinates/sunrise/sunset windows.
- `[modbus]` & `[inverter:NAME]`: Global Modbus settings and per-inverter host/port/unit.
- `[pushover]`, `[healthchecks]`: Enable flags and credentials for each notifier.
- `[health]`: Thresholds for peer comparison, low PAC/Vdc checks, etc.
- `[solaredge_api]`: Enable flag, API key/site ID, and optional night skipping.
- `[state]`: Path to the SQLite database (`~/.solaredge_monitor_state.db` by default).
- `[simulation]` and `[simulation:scenario]`: Lists of inverters plus per-field overrides (PAC/Vdc/total_wh/optimizers). Include `simulated_time` to force a specific timestamp.
- `[retention]`: `snapshot_days`, `summary_days`, and `vacuum_after_prune` control how `maintain-db` prunes the DB.

## CLI Commands

Run from the repo root:

- `python -m solaredge_monitor.main --config solaredge_monitor.conf health`: One-shot real run (default).
- `python -m solaredge_monitor.main --config ... simulate --scenario fault`: Run using `[simulation:fault]` data.
- `python -m solaredge_monitor.main --config ... notify-test --mode fault`: Send test alerts.
- `python -m solaredge_monitor.main --config ... maintain-db`: Prune historical data per `[retention]`. Override with `--snapshot-days`, `--summary-days`, `--no-vacuum` as needed.

Use `--debug` for verbose logs, `--json` to print Modbus snapshots as JSON, and `--quiet` to suppress stdout output.

## Testing

Pytest covers daylight logic, daily summaries, simulated readers/APIs, the new SQLite `AppState`, and retention parsing/maintenance. Run `pytest` locally (the sandbox lacks a writable `/tmp`, so tests can’t run here).
