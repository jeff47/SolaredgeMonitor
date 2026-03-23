from __future__ import annotations

from pathlib import Path

import pytest

from solaredge_monitor.cli import build_parser
from solaredge_monitor.config import Config


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "solar.conf"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_parser_supports_commands_and_flags():
    parser = build_parser()

    args = parser.parse_args(
        [
            "--config",
            "custom.conf",
            "--debug",
            "--quiet",
            "simulate",
            "--scenario",
            "sunset",
        ]
    )

    assert args.config == "custom.conf"
    assert args.debug is True
    assert args.quiet is True
    assert args.command == "simulate"
    assert args.scenario == "sunset"


def test_cli_parser_maintain_db_flags():
    parser = build_parser()

    args = parser.parse_args(
        [
            "maintain-db",
            "--snapshot-days",
            "10",
            "--summary-days",
            "20",
            "--no-vacuum",
        ]
    )

    assert args.command == "maintain-db"
    assert args.snapshot_days == 10
    assert args.summary_days == 20
    assert args.no_vacuum is True


def test_config_requires_modbus_section(tmp_path: Path):
    path = _write_config(
        tmp_path,
        """
[health]
low_vdc_threshold = 40
""".strip(),
    )

    with pytest.raises(ValueError, match=r"\[modbus\] section missing"):
        Config.load(str(path))


def test_config_requires_inverter_section(tmp_path: Path):
    path = _write_config(
        tmp_path,
        """
[modbus]
inverters = INV-A
""".strip(),
    )

    with pytest.raises(ValueError, match=r"Missing section \[inverter:INV-A\]"):
        Config.load(str(path))


def test_config_parses_simulation_weather_logging_and_api_options(tmp_path: Path):
    path = _write_config(
        tmp_path,
        """
[modbus]
inverters = INV-A, INV-B
retries = 5
timeout = 4.5
skip_modbus_at_night = false

[inverter:INV-A]
host = 1.1.1.1
port = 1503
unit = 2
expected_optimizers = 12
array_kw_dc = 5.5
ac_capacity_kw = 4.2
tilt_deg = 25
azimuth_deg = 190

[inverter:INV-B]
host = 1.1.1.2

[solaredge_api]
enabled = true
solaredge_api_key = secret
solaredge_site_id = 123
skip_se_api_at_night = true

[simulation]
scenario = sunset
simulated_time = 2024-06-01T20:15:00
inverter_status = INV-A:4, INV-B:2

[simulation:sunset]
inverter_pac_w = INV-A:50, INV-B:0

[weather]
enabled = true
latitude = 40.0
longitude = -74.0
array_kw_dc = 10
ac_capacity_kw = 7.6
log_path = ./weather.jsonl

[logging]
console_level = DEBUG
console_quiet = true
debug_modules = pymodbus, requests
structured_enabled = true
structured_path = ./structured.jsonl
""".strip(),
    )

    cfg = Config.load(str(path))

    assert cfg.modbus.retries == 5
    assert cfg.modbus.timeout == 4.5
    assert cfg.modbus.skip_modbus_at_night is False
    assert [inv.name for inv in cfg.modbus.inverters] == ["INV-A", "INV-B"]
    assert cfg.modbus.inverters[0].expected_optimizers == 12
    assert cfg.modbus.inverters[0].ac_capacity_kw == 4.2
    assert cfg.health.identical_alert_gate_minutes == 60
    assert cfg.health.repeat_alert_interval_minutes == 720

    assert cfg.solaredge_api.enabled is True
    assert cfg.solaredge_api.api_key == "secret"
    assert cfg.solaredge_api.site_id == "123"
    assert cfg.solaredge_api.skip_at_night is True

    assert cfg.simulation.scenario == "sunset"
    assert cfg.simulation.simulated_time == "2024-06-01T20:15:00"
    assert cfg.simulation.settings["inverter_status"] == "INV-A:4, INV-B:2"
    assert cfg.simulation.scenarios["sunset"]["inverter_pac_w"] == "INV-A:50, INV-B:0"

    assert cfg.weather.enabled is True
    assert cfg.weather.latitude == 40.0
    assert cfg.weather.longitude == -74.0
    assert cfg.weather.log_path == "./weather.jsonl"

    assert cfg.logging.console_level == "DEBUG"
    assert cfg.logging.console_quiet is True
    assert cfg.logging.debug_modules == ["pymodbus", "requests"]
    assert cfg.logging.structured_enabled is True
    assert cfg.logging.structured_path == "./structured.jsonl"


def test_config_accepts_explicit_false_boolean_values(tmp_path: Path):
    path = _write_config(
        tmp_path,
        """
[modbus]
inverters = INV-A
skip_modbus_at_night = false

[inverter:INV-A]
host = 1.1.1.1

[pushover]
enabled = false
""".strip(),
    )

    cfg = Config.load(str(path))

    assert cfg.modbus.skip_modbus_at_night is False
    assert cfg.pushover.enabled is False


def test_config_rejects_invalid_boolean_values(tmp_path: Path):
    path = _write_config(
        tmp_path,
        """
[modbus]
inverters = INV-A
skip_modbus_at_night = tru

[inverter:INV-A]
host = 1.1.1.1
""".strip(),
    )

    with pytest.raises(ValueError, match="Invalid boolean value"):
        Config.load(str(path))
