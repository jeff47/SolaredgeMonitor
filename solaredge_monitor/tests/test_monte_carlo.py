# solaredge_monitor/tests/test_monte_carlo.py
import random

from solaredge_monitor.tests.fake_reader import MockModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.logging import ConsoleLog, get_logger

ConsoleLog(level="INFO", quiet=True).setup()
LOG = get_logger("monte")


class DummyCfg:
    peer_ratio_threshold = 0.60
    min_production_for_peer_check = 0.5
    low_light_peer_skip_threshold = 0.2
    low_pac_threshold = 1.0
    low_vdc_threshold = 50
    min_alert_sun_el_deg = None
    alert_irradiance_floor_wm2 = 30.0


def _eval(values):
    evaluator = HealthEvaluator(DummyCfg(), LOG)
    reader = MockModbusReader(values, LOG)
    capacities = {name: 1.0 for name in values.keys()}
    return evaluator.evaluate(reader.read_all(), capacity_by_name=capacities)


def test_monte_carlo_randomized():
    """
    Randomized stress test — checks no crashes and basic invariants.
    """
    rng = random.Random(0xC0FFEE)

    for _ in range(500):
        A_pac = rng.uniform(0, 6000)
        B_pac = rng.uniform(0, 6000)
        A_vdc = rng.uniform(0, 450)
        B_vdc = rng.uniform(0, 450)

        values = {
            "A": {"status": 4, "pac_w": A_pac, "vdc_v": A_vdc},
            "B": {"status": 4, "pac_w": B_pac, "vdc_v": B_vdc},
        }

        health = _eval(values)
        max_pac = max(A_pac, B_pac)

        low_light_w = 1_000 * (DummyCfg.low_light_peer_skip_threshold / 100.0)
        # Invariant 1: low light should always be OK
        if max_pac < low_light_w:
            assert health.system_ok

        # Invariant 2: extremely low PAC (<1W) but status=4 should not crash
        assert health is not None

        # Invariant 3: Real peer mismatches should fail when > threshold
        min_prod_w = 1_000 * (DummyCfg.min_production_for_peer_check / 100.0)
        if (
            A_pac > min_prod_w
            and B_pac > min_prod_w
            and A_vdc >= 50
            and B_vdc >= 50
        ):
            ratio = min(A_pac, B_pac) / max_pac
            if ratio < DummyCfg.peer_ratio_threshold:
                assert not health.system_ok
            else:
                assert health.system_ok
