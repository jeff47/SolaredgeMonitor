# tests/test_basic_reader.py

from .fake_reader import MockModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.logging import ConsoleLog, get_logger


# Minimal config object for HealthEvaluator
class DummyCfg:
    peer_ratio_threshold = 0.6
    min_production_for_peer_check = 0.5
    low_light_peer_skip_threshold = 0.2
    low_pac_threshold = 1.0
    low_vdc_threshold = 50
    min_alert_sun_el_deg = None
    alert_irradiance_floor_wm2 = 30.0


def test_basic_reader_and_health():
    # Prepare logging for tests
    ConsoleLog(level="INFO", quiet=True).setup()
    log = get_logger("test")

    reader = MockModbusReader({
        "INV-A": {"pac_w": 1500, "status": 4, "vdc_v": 400, "idc_a": 3.5},
        "INV-B": {"pac_w": 1300, "status": 4, "vdc_v": 380, "idc_a": 3.2},
    }, log)

    evaluator = HealthEvaluator(DummyCfg(), log)

    # Read from mock
    readings = reader.read_all()
    capacities = {name: 1.0 for name in readings}

    # Basic sanity checks
    assert "INV-A" in readings
    assert "INV-B" in readings
    assert readings["INV-A"].pac_w == 1500

    # Evaluate health
    health = evaluator.evaluate(readings, capacity_by_name=capacities)

    # Expectations:
    #  - both producing above threshold
    #  - peer mismatch should not trip
    assert health.system_ok, f"Expected system OK, got: {health}"

    # All individual inverters should be OK
    for inv_name, inv_state in health.per_inverter.items():
        assert inv_state.inverter_ok, f"{inv_name} unexpectedly marked bad: {inv_state.reason}"
