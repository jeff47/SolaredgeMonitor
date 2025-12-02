# solaredge_monitor/tests/test_golden_cases.py

import json
from pathlib import Path

import pytest

from solaredge_monitor.tests.fake_reader import MockModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.logging import ConsoleLog, get_logger


ConsoleLog(level="INFO", quiet=True).setup()
LOG = get_logger("golden")
CASES_DIR = Path(__file__).with_name("golden_cases")


class DummyCfg:
    peer_ratio_threshold = 0.60
    min_production_for_peer_check = 200
    low_light_peer_skip_threshold = 20
    low_pac_threshold = 10
    low_vdc_threshold = 50
    min_alert_sun_el_deg = None
    min_alert_irradiance_wm2 = 1.0


def _load_cases():
    if not CASES_DIR.exists():
        raise AssertionError(f"Golden case directory missing: {CASES_DIR}")

    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        with path.open() as fh:
            data = json.load(fh)
        data["_file"] = path.name
        cases.append(pytest.param(data, id=data.get("id", path.stem)))

    if not cases:
        raise AssertionError(f"No golden case files found in {CASES_DIR}")
    return cases


@pytest.mark.parametrize("case", _load_cases())
def test_golden_cases(case):
    evaluator = HealthEvaluator(DummyCfg(), LOG)
    reader = MockModbusReader(case["readings"], LOG)
    health = evaluator.evaluate(reader.read_all())

    expected = case["expected"]
    assert health.system_ok == expected["system_ok"], case.get("description")

    expected_per = expected.get("per_inverter", {})
    assert set(health.per_inverter.keys()) == set(expected_per.keys())

    for name, inv_expected in expected_per.items():
        inv_health = health.per_inverter[name]
        assert inv_health.inverter_ok == inv_expected["inverter_ok"]

        if inv_expected.get("reason_should_be_none"):
            assert inv_health.reason is None

        reason_exact = inv_expected.get("reason")
        if reason_exact is not None:
            assert inv_health.reason == reason_exact

        reason_contains = inv_expected.get("reason_contains")
        if reason_contains is not None:
            assert inv_health.reason is not None
            assert reason_contains in inv_health.reason
