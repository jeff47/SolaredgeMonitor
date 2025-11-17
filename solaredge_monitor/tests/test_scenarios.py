# solaredge_monitor/tests/test_scenarios.py

import pytest
from solaredge_monitor.tests.fake_reader import MockModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.util.logging import setup_logging, get_logger


# Minimal health config for evaluator
class DummyCfg:
    peer_ratio_threshold = 0.60
    min_production_for_peer_check = 200
    low_light_peer_skip_threshold = 20

def _eval(values):
    """Helper: run evaluation on a dict of inverter->value mappings."""
    setup_logging(debug=False)
    log = get_logger("test")
    evaluator = HealthEvaluator(DummyCfg(), log)
    reader = MockModbusReader(values, log)
    return evaluator.evaluate(reader.read_all())


# ------------------------------------------------------------------------------
# 1. Both producing normally
# ------------------------------------------------------------------------------
def test_both_producing_normal():
    health = _eval({
        "A": {"status": 4, "pac_w": 1500, "vdc_v": 400},
        "B": {"status": 4, "pac_w": 1400, "vdc_v": 390},
    })
    assert health.system_ok


# ------------------------------------------------------------------------------
# 2. Both producing low (cloudy)
# ------------------------------------------------------------------------------
def test_cloudy_both_low():
    health = _eval({
        "A": {"status": 4, "pac_w": 30, "vdc_v": 350},
        "B": {"status": 4, "pac_w": 25, "vdc_v": 360},
    })
    assert health.system_ok


# ------------------------------------------------------------------------------
# 3. One producing, one sleeping (modbus-only: unhealthy)
# ------------------------------------------------------------------------------
def test_one_producing_one_sleeping():
    health = _eval({
        "A": {"status": 4, "pac_w": 300, "vdc_v": 400},
        "B": {"status": 2, "pac_w": 0,   "vdc_v": 410},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 4. Peer mismatch
# ------------------------------------------------------------------------------
def test_peer_mismatch():
    health = _eval({
        "A": {"status": 4, "pac_w": 1500, "vdc_v": 400},
        "B": {"status": 4, "pac_w": 200,  "vdc_v": 390},
    })
    assert not health.system_ok
    assert not health.per_inverter["B"].inverter_ok


# ------------------------------------------------------------------------------
# 5. Producing but very low PAC
# ------------------------------------------------------------------------------
def test_low_pac_producing():
    health = _eval({
        "A": {"status": 4, "pac_w": 5, "vdc_v": 400},
        "B": {"status": 4, "pac_w": 900, "vdc_v": 395},
    })
    assert not health.system_ok
    assert not health.per_inverter["A"].inverter_ok


# ------------------------------------------------------------------------------
# 6. Fault state
# ------------------------------------------------------------------------------
def test_fault_state():
    health = _eval({
        "A": {"status": 7, "pac_w": 0, "vdc_v": 0},
        "B": {"status": 4, "pac_w": 800, "vdc_v": 390},
    })
    assert not health.system_ok
    assert not health.per_inverter["A"].inverter_ok


# ------------------------------------------------------------------------------
# 7. Both sleeping (modbus-only: unhealthy)
# ------------------------------------------------------------------------------
def test_both_sleeping():
    health = _eval({
        "A": {"status": 2, "pac_w": 0, "vdc_v": 0},
        "B": {"status": 2, "pac_w": 0, "vdc_v": 0},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 8. Low Vdc < 50 V
# ------------------------------------------------------------------------------
def test_low_vdc():
    health = _eval({
        "A": {"status": 4, "pac_w": 600, "vdc_v": 20},
        "B": {"status": 4, "pac_w": 650, "vdc_v": 380},
    })
    assert not health.system_ok
    assert not health.per_inverter["A"].inverter_ok


# ------------------------------------------------------------------------------
# 9. Borderline Vdc exactly passing
# ------------------------------------------------------------------------------
def test_borderline_vdc():
    health = _eval({
        "A": {"status": 4, "pac_w": 600, "vdc_v": 51},
        "B": {"status": 4, "pac_w": 650, "vdc_v": 52},
    })
    assert health.system_ok


# ------------------------------------------------------------------------------
# 10. Vdc = 0
# ------------------------------------------------------------------------------
def test_vdc_zero():
    health = _eval({
        "A": {"status": 4, "pac_w": 600, "vdc_v": 0},
        "B": {"status": 4, "pac_w": 650, "vdc_v": 390},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 11. Both Vdc low
# ------------------------------------------------------------------------------
def test_both_vdc_low():
    health = _eval({
        "A": {"status": 4, "pac_w": 600, "vdc_v": 10},
        "B": {"status": 4, "pac_w": 650, "vdc_v": 12},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 12. One inverter offline
# ------------------------------------------------------------------------------
def test_inverter_offline():
    health = _eval({
        "A": {"status": 4, "pac_w": 600, "vdc_v": 380},
        "B": None,
    })
    assert not health.system_ok
    assert not health.per_inverter["B"].inverter_ok


# ------------------------------------------------------------------------------
# 13. Starting vs producing (modbus-only: unhealthy)
# ------------------------------------------------------------------------------
def test_starting_vs_producing():
    health = _eval({
        "A": {"status": 3, "pac_w": 0, "vdc_v": 380},
        "B": {"status": 4, "pac_w": 800, "vdc_v": 380},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 14. Throttled vs producing
# ------------------------------------------------------------------------------
def test_throttled_ok():
    health = _eval({
        "A": {"status": 5, "pac_w": 600, "vdc_v": 380},
        "B": {"status": 4, "pac_w": 620, "vdc_v": 385},
    })
    assert health.system_ok


# ------------------------------------------------------------------------------
# 15. Shutting down
# ------------------------------------------------------------------------------
def test_shutting_down():
    health = _eval({
        "A": {"status": 6, "pac_w": 10, "vdc_v": 380},
        "B": {"status": 4, "pac_w": 800, "vdc_v": 390},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 16. Negative PAC
# ------------------------------------------------------------------------------
def test_negative_pac():
    health = _eval({
        "A": {"status": 4, "pac_w": -10, "vdc_v": 380},
        "B": {"status": 4, "pac_w": 900, "vdc_v": 390},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 17. High PAC anomaly
# ------------------------------------------------------------------------------
def test_high_pac_anomaly():
    health = _eval({
        "A": {"status": 4, "pac_w": 50000, "vdc_v": 420},
        "B": {"status": 4, "pac_w": 900,   "vdc_v": 390},
    })
    assert not health.system_ok


# ------------------------------------------------------------------------------
# 18. Model mismatch but both normal
# ------------------------------------------------------------------------------
def test_model_mismatch_ratio_ok():
    health = _eval({
        "A": {"status": 4, "pac_w": 5200, "vdc_v": 420},
        "B": {"status": 4, "pac_w": 5000, "vdc_v": 400},
    })
    assert health.system_ok


# ------------------------------------------------------------------------------
# 19. Throttled high production
# ------------------------------------------------------------------------------
def test_throttled_high():
    health = _eval({
        "A": {"status": 5, "pac_w": 3000, "vdc_v": 420},
        "B": {"status": 4, "pac_w": 3100, "vdc_v": 415},
    })
    assert health.system_ok


# ------------------------------------------------------------------------------
# 20. Peer mismatch but below min production threshold
# ------------------------------------------------------------------------------
def test_peer_below_threshold():
    health = _eval({
        "A": {"status": 4, "pac_w": 11, "vdc_v": 350},
        "B": {"status": 4, "pac_w": 1,  "vdc_v": 350},
    })
    assert health.system_ok


def test_both_low_pac_cloudy():
    health = _eval({
        "A": {"status": 4, "pac_w": 5, "vdc_v": 350},
        "B": {"status": 4, "pac_w": 4, "vdc_v": 350},
    })
    assert health.system_ok

def test_one_low_one_high_fault():
    health = _eval({
        "A": {"status": 4, "pac_w": 900, "vdc_v": 350},
        "B": {"status": 4, "pac_w": 5,   "vdc_v": 350},
    })
    assert not health.system_ok

def test_low_light_asymmetry_still_ok():
    health = _eval({
        "A": {"status": 4, "pac_w": 12, "vdc_v": 350},
        "B": {"status": 4, "pac_w": 1,  "vdc_v": 350},
    })
    assert health.system_ok

def test_midrange_asymmetry_should_fail():
    health = _eval({
        "A": {"status": 4, "pac_w": 100, "vdc_v": 350},
        "B": {"status": 4, "pac_w": 5,   "vdc_v": 350},
    })
    assert not health.system_ok
