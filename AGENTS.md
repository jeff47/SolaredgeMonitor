# Project Agent Instructions

## Project Structure

- This is a Python SolarEdge monitoring application. Runtime orchestration is in `solaredge_monitor/main.py`.
- Health checks and production comparisons are implemented in `solaredge_monitor/services/health_evaluator.py`.
- Configuration defaults and parsing are in `solaredge_monitor/config.py`; the tracked template is `solaredge_monitor.conf.example`.
- Tests live in `solaredge_monitor/tests/` and use pytest.

## Alerting Invariants

- Keep equipment faults distinct from production heuristics. Offline inverters and inverter fault status must not be hidden by shading or low-light suppression.
- PAC and peer-comparison thresholds are percentages of each inverter's AC capacity; preserve that basis when changing threshold calculations.
- The irradiance floor suppresses PAC-related checks when either GHI or POA is at or below the configured floor. Preserve the either-source behavior to handle stale or orientation-specific irradiance estimates.
- Directional peer-mismatch thresholds use solar elevation and azimuth: azimuth below 180 degrees is morning; 180 degrees and above is evening.
- Keep the directional sun-angle suppression scoped to peer mismatches. Do not extend it to low-PAC, low-voltage, or startup alerts without an explicit request.
- WeatherClient derives solar position with Astral using the current time and configured coordinates. If weather, coordinates, Astral, or the angle values are unavailable, do not suppress peer comparisons based on angle.
- Daylight grace is based on configured location, timezone, and sunrise/sunset; avoid replacing it with fixed clock-time rules without a specific need.
- Alert persistence, repeat notifications, and recovery notifications are managed by `AlertStateManager`; test those transitions when changing alert lifecycle behavior.
- Mark angle-suppressed peer comparisons as unevaluated, not healthy. Do not advance recovery counters, close an open peer-mismatch incident, or send an all-clear ping for that skipped comparison; test suppression followed by a real recovery.

## Configuration And Secrets

- The local `solaredge_monitor.conf` is not the shared template and may contain API keys, notifier credentials, and local paths. Never copy or print its secrets.
- Structured JSONL logs can include inverter readings, alerts, and raw cloud payloads. Inspect only the fields needed for diagnosis and avoid dumping sensitive payloads.
- When adding a setting, update `HealthConfig` and its parser, add it to the example configuration where appropriate, and test parsing.

## Validation

- Run focused tests for the changed behavior, then run the full suite with `pytest -q`.
- Health and config regression tests are in `solaredge_monitor/tests/test_fault_cases.py` and `solaredge_monitor/tests/test_cli_and_config.py`.
- Use `python -m solaredge_monitor.main --config <path> health` for a one-shot live check; use `simulate --scenario <name>` or a configured `simulated_time` to exercise alert logic without live inverter data.
