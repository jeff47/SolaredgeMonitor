# solaredge_monitor/tests/test_fault_cases.py

from .fake_reader import MockModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.logging import ConsoleLog, get_logger


class DummyCfg:
    peer_ratio_threshold = 0.6          # If one inverter <60% of peer → fault
    min_production_for_peer_check = 2.0  # percent of AC capacity (e.g., 20 W @ 1 kW)
    low_light_peer_skip_threshold = 0.2  # percent of AC capacity (e.g., 2 W @ 1 kW)
    low_pac_threshold = 1.0              # percent of AC capacity (e.g., 10 W @ 1 kW)
    low_vdc_threshold = 50
    min_alert_sun_el_deg = None
    alert_irradiance_floor_wm2 = 30.0


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

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), capacity_by_name=caps)

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

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), capacity_by_name=caps)

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

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), capacity_by_name=caps)

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert "PAC" in health.per_inverter["INV-A"].reason


def test_low_pac_suppressed_by_weather_gate():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 4, "vdc_v": 395},
    }, evaluator.log)

    health = evaluator.evaluate(
        reader.read_all(),
        capacity_by_name={"INV-A": 10.0, "INV-B": 10.0},
        pac_alert_suppression={"INV-A": True},
    )

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok


# ---------------------------------------------------------------------------
# 4. Environmental condition – low PAC everywhere → peer check skipped
# ---------------------------------------------------------------------------

def test_both_low_pac_environmental_skip_peer_check():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 150, "vdc_v": 400},
        "INV-B": {"status": 4, "pac_w": 140, "vdc_v": 390},
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), capacity_by_name=caps)

    # Should NOT flag peer mismatch because both below min_production_for_peer_check
    assert health.system_ok


# ---------------------------------------------------------------------------
# 5. Producing inverter with None power readings — no spurious fault
# ---------------------------------------------------------------------------

def test_producing_inverter_null_pac_not_faulted():
    """status=4 with pac_w=None should not trigger a low_pac alert — can't fault what can't be read."""
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "vdc_v": 380},  # pac_w absent → None
        "INV-B": {"status": 4, "pac_w": 800, "vdc_v": 380},
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all(), capacity_by_name={"INV-A": 1.0, "INV-B": 1.0})

    assert health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-A"].fault_code is None


def test_producing_inverter_null_vdc_not_faulted():
    """status=4 with vdc_v=None should not trigger a low_vdc alert — can't fault what can't be read."""
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 500},  # vdc_v absent → None
    }, evaluator.log)

    health = evaluator.evaluate(reader.read_all(), capacity_by_name={"INV-A": 1.0})

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-A"].fault_code is None


# ---------------------------------------------------------------------------
# 6. Low Vdc fault
# ---------------------------------------------------------------------------

def test_low_vdc():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 600, "vdc_v": 20},  # fault
        "INV-B": {"status": 4, "pac_w": 650, "vdc_v": 380},
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), capacity_by_name=caps)

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert "Vdc" in health.per_inverter["INV-A"].reason


# ---------------------------------------------------------------------------
# 7. Offline inverter (None reading)
# ---------------------------------------------------------------------------

def test_inverter_offline():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 700, "vdc_v": 390},
        "INV-B": None,  # offline — FakeInverterReader passes None through natively
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), capacity_by_name=caps)

    assert not health.system_ok
    assert not health.per_inverter["INV-B"].inverter_ok
    assert "offline" in health.per_inverter["INV-B"].reason.lower()


# ---------------------------------------------------------------------------
# 8. Low irradiance suppression should allow sleeping/low-Vdc without alerts
# ---------------------------------------------------------------------------

def test_dark_irradiance_suppresses_sleeping_and_low_vdc():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 2, "pac_w": 0, "vdc_v": 0},   # sleeping
        "INV-B": {"status": 4, "pac_w": 0, "vdc_v": 20},  # producing but dark
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), dark_irradiance=True, capacity_by_name=caps)

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok


# ---------------------------------------------------------------------------
# 9. Faults should still alert even when irradiance is zero
# ---------------------------------------------------------------------------

def test_dark_irradiance_does_not_hide_fault_state():
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 7, "pac_w": 0, "vdc_v": 0},  # Fault
        "INV-B": {"status": 2, "pac_w": 0, "vdc_v": 0},
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), dark_irradiance=True, capacity_by_name=caps)

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok


# ---------------------------------------------------------------------------
# 10. Grace window (sunset/sunrise) should suppress low-Vdc alerts
# ---------------------------------------------------------------------------

def test_grace_window_suppresses_low_vdc():
    """low_vdc faults should be cleared during sunset/sunrise grace windows."""
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 0, "vdc_v": 20},  # Vdc collapsing at sunset
        "INV-B": {"status": 4, "pac_w": 0, "vdc_v": 18},
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), low_light_grace=True, capacity_by_name=caps)

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok


def test_low_vdc_still_alerts_outside_grace_window():
    """low_vdc faults should fire during normal daylight hours."""
    evaluator = _mk_evaluator()

    reader = MockModbusReader({
        "INV-A": {"status": 4, "pac_w": 0, "vdc_v": 20},  # faulted mid-day
        "INV-B": {"status": 4, "pac_w": 650, "vdc_v": 380},
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), low_light_grace=False, capacity_by_name=caps)

    assert not health.system_ok
    assert not health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok


# ---------------------------------------------------------------------------
# 11. Low sun angle should suppress sleeping alerts
# ---------------------------------------------------------------------------

def test_low_sun_angle_suppresses_sleeping_status():
    class AngleCfg(DummyCfg):
        min_alert_sun_el_deg = 6.0

    ConsoleLog(level="INFO", quiet=True).setup()
    evaluator = HealthEvaluator(AngleCfg(), get_logger("test"))

    reader = MockModbusReader({
        "INV-A": {"status": 2, "pac_w": 0, "vdc_v": 0},
        "INV-B": {"status": 6, "pac_w": 0, "vdc_v": 0},
    }, evaluator.log)

    caps = {"INV-A": 1.0, "INV-B": 1.0}
    health = evaluator.evaluate(reader.read_all(), sun_elevation_deg=0.5, capacity_by_name=caps)

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok
    assert health.per_inverter["INV-B"].inverter_ok


# ---------------------------------------------------------------------------
# 12. Low sun angle should suppress starting status
# ---------------------------------------------------------------------------

def test_low_sun_angle_suppresses_starting_status():
    class AngleCfg(DummyCfg):
        min_alert_sun_el_deg = 6.0

    ConsoleLog(level="INFO", quiet=True).setup()
    evaluator = HealthEvaluator(AngleCfg(), get_logger("test"))

    reader = MockModbusReader({
        "INV-A": {"status": 3, "pac_w": 0, "vdc_v": 0},  # Starting
    }, evaluator.log)

    caps = {"INV-A": 1.0}
    health = evaluator.evaluate(reader.read_all(), sun_elevation_deg=0.2, capacity_by_name=caps)

    assert health.system_ok
    assert health.per_inverter["INV-A"].inverter_ok


# ---------------------------------------------------------------------------
# 13. GHI-derived dark_irradiance should suppress sleeping but not when above threshold
# ---------------------------------------------------------------------------

def test_irradiance_floor_controls_dark_irradiance_gate():
    class IrrCfg(DummyCfg):
        alert_irradiance_floor_wm2 = 10.0
        min_alert_sun_el_deg = None

    ConsoleLog(level="INFO", quiet=True).setup()
    evaluator = HealthEvaluator(IrrCfg(), get_logger("test"))

    base_readings = {
        "INV-A": {"status": 2, "pac_w": 0, "vdc_v": 0},  # Sleeping
    }

    # Below threshold (GHI <= 10): should suppress alert
    dark_flag = 5.0 <= IrrCfg.alert_irradiance_floor_wm2
    caps = {"INV-A": 1.0}
    health_dark = evaluator.evaluate(
        MockModbusReader(base_readings, evaluator.log).read_all(),
        dark_irradiance=dark_flag,
        sun_elevation_deg=10.0,  # day
        capacity_by_name=caps,
    )
    assert health_dark.system_ok
    assert health_dark.per_inverter["INV-A"].inverter_ok

    # Above threshold (GHI > 10): should alert
    bright_flag = 12.0 <= IrrCfg.alert_irradiance_floor_wm2
    health_bright = evaluator.evaluate(
        MockModbusReader(base_readings, evaluator.log).read_all(),
        dark_irradiance=bright_flag,
        sun_elevation_deg=10.0,  # day
        capacity_by_name=caps,
    )
    assert not health_bright.system_ok
    assert not health_bright.per_inverter["INV-A"].inverter_ok
