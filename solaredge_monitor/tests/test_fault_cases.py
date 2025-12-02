# solaredge_monitor/tests/test_fault_cases.py

from .fake_reader import MockModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.logging import ConsoleLog, get_logger


class DummyCfg:
    peer_ratio_threshold = 0.6          # If one inverter <60% of peer → fault
    min_production_for_peer_check = 200 # Skip peer check if both below this
    low_light_peer_skip_threshold = 20   # Peer checks skipped under this PAC
    low_pac_threshold = 10
    low_vdc_threshold = 50
    min_alert_sun_el_deg = None
    min_alert_irradiance_wm2 = 1.0


def _mk_evaluator():
    ConsoleLog(level="INFO", quiet=True).setup()
    return HealthEvaluator(DummyCfg(), get_logger("test"))


# ---------------------------------------------------------------------------
# 1. Mismatched status (one producing, one sleeping)
# ---------------------------------------------------------------------------

def test_status_mismatch():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 800, "vdc_v": 400},
        "INV-B": {"status": 2, "pac_w": 0,   "vdc_v": 410},  # sleeping
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all())

    assert not health.system_ok
    assert not health.per_inverter["INV-B"].inverter_ok
    assert health.per_inverter["INV-A"].inverter_ok


# ---------------------------------------------------------------------------
# 2. Peer mismatch (one producing far less than another)
# ---------------------------------------------------------------------------

def test_peer_mismatch_low_production_outlier():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 1500, "vdc_v": 400},
        "INV-B": {"status": 4, "pac_w": 200,  "vdc_v": 390},  # < ratio threshold
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all())

    assert not health.system_ok
    assert not health.per_inverter["INV-B"].inverter_ok
    assert "ratio" in health.per_inverter["INV-B"].reason


# ---------------------------------------------------------------------------
# 3. Low PAC while producing
# ---------------------------------------------------------------------------

def test_low_pac_producing():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 2, "vdc_v": 400},
        "INV-B": {"status": 4, "pac_w": 900, "vdc_v": 395},
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all())

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert "PAC" in health.per_inverter["INV-A"].reason


# ---------------------------------------------------------------------------
# 4. Environmental condition – low PAC everywhere → peer check skipped
# ---------------------------------------------------------------------------

def test_both_low_pac_environmental_skip_peer_check():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 50, "vdc_v": 400},
        "INV-B": {"status": 4, "pac_w": 40, "vdc_v": 390},
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all())

    # Should NOT flag peer mismatch because both below min_production_for_peer_check
    assert health.system_ok


# ---------------------------------------------------------------------------
# 5. Low Vdc fault
# ---------------------------------------------------------------------------

def test_low_vdc():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 600, "vdc_v": 20},  # fault
        "INV-B": {"status": 4, "pac_w": 650, "vdc_v": 380},
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all())

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert "Vdc" in health.per_inverter["INV-A"].reason


# ---------------------------------------------------------------------------
# 6. Offline inverter (None reading)
# ---------------------------------------------------------------------------

def test_inverter_offline():
    evaluator = _mk_evaluator()

    # Simulate reader returning None for INV-B
    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 700, "vdc_v": 390},
        "INV-B": None,  # offline
    }, evaluator.log)

    # Patch FakeReader so it passes None correctly
    old_values = reader.values
    def read_all_override():
        out = {}
        for k, v in old_values.items():
            if v is None:
                out[k] = None
            else:
                out[k] = out.get(k) or reader._make_snapshot(k, v)
        return out

    # Add helper to FakeReader
    def _make_snapshot(self, name, vals):
        from solaredge_monitor.models.inverter import InverterSnapshot
        from datetime import datetime, timezone
        return InverterSnapshot(
            name=name,
            serial=f"SIM-{name}",
            model="SIMMODEL",
            status=vals.get("status", 4),
            vendor_status=None,
            pac_w=vals.get("pac_w", 0.0),
            vdc_v=vals.get("vdc_v", 0.0),
            idc_a=vals.get("idc_a", 0.0),
            total_wh=vals.get("total_wh", 0.0),
            error=None,
            timestamp=datetime.now(timezone.utc),
        )
    reader._make_snapshot = _make_snapshot.__get__(reader)

    reader.read_all = read_all_override

    health = evaluator.evaluate(reader.read_all())

    assert not health.system_ok
    assert not health.per_inverter["INV-B"].inverter_ok
    assert "offline" in health.per_inverter["INV-B"].reason.lower()


# ---------------------------------------------------------------------------
# 7. Low irradiance suppression should allow sleeping/low-Vdc without alerts
# ---------------------------------------------------------------------------

def test_dark_irradiance_suppresses_sleeping_and_low_vdc():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 2, "pac_w": 0, "vdc_v": 0},   # sleeping
        "INV-B": {"status": 4, "pac_w": 0, "vdc_v": 20},  # producing but dark
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all(), dark_irradiance=True)

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok


# ---------------------------------------------------------------------------
# 8. Faults should still alert even when irradiance is zero
# ---------------------------------------------------------------------------

def test_dark_irradiance_does_not_hide_fault_state():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 7, "pac_w": 0, "vdc_v": 0},  # Fault
        "INV-B": {"status": 2, "pac_w": 0, "vdc_v": 0},
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all(), dark_irradiance=True)

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok
