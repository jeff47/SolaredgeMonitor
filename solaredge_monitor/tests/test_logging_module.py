import json
import logging
import os
import tempfile

from solaredge_monitor.logging import ConsoleLog, RunLogEntry, StructuredLog


def test_structured_log_writes_json():
    # Use a workspace temp dir to avoid system temp constraints.
    with tempfile.TemporaryDirectory(dir=".") as td:
        log_path = os.path.join(td, "structured.log")
        entry = RunLogEntry(
            timestamp="2024-01-01T00:00:00Z",
            daylight_phase="day",
            daylight_context={"phase": "day", "in_grace_window": False},
            inverter_snapshots={"INV1": {"pac_w": 100}},
            weather_snapshot={"ghi_wm2": 123.0},
            weather_expectations={"INV1": {"expected_ac_kw": 0.1}},
            residuals={"INV1": {"pac_w": 100, "expected_ac_w": 120, "residual_w": -20, "ratio": 0.83}},
            health={"INV1": {"status": "ok"}},
            alerts=[{"message": "none"}],
            cloud_inventory=None,
            optimizer_counts=None,
        )
        StructuredLog(log_path, enabled=True).write(entry)
        with open(log_path, "r", encoding="utf-8") as fh:
            line = fh.read().strip()
        assert line
        payload = json.loads(line)
        assert payload["timestamp"] == entry.timestamp
        assert payload["inverter_snapshots"]["INV1"]["pac_w"] == 100
        assert payload["weather_snapshot"]["ghi_wm2"] == 123.0
        assert payload["weather_expectations"]["INV1"]["expected_ac_kw"] == 0.1


def test_console_log_quiet_skips_handlers():
    root = logging.getLogger()
    orig_handlers = list(root.handlers)
    orig_level = root.level
    try:
        log = ConsoleLog(level="INFO", quiet=True).setup()
        assert log.name == "solaredge"
        assert root.handlers == []
    finally:
        root.handlers.clear()
        root.handlers.extend(orig_handlers)
        root.setLevel(orig_level)
