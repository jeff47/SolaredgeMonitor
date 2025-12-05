# solaredge_monitor/tests/test_weather_suppression.py

from datetime import datetime, timezone

from solaredge_monitor.config import HealthConfig
from solaredge_monitor.logging import ConsoleLog, get_logger
from solaredge_monitor.main import _compute_pac_alert_suppression
from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.models.weather import InverterExpectation, WeatherEstimate, WeatherSnapshot
from solaredge_monitor.services.health_evaluator import HealthEvaluator


ConsoleLog(level="INFO", quiet=True).setup()
LOG = get_logger("weather-suppression-test")


def _snapshot(pac_w: float) -> InverterSnapshot:
    return InverterSnapshot(
        name="INV",
        serial="SIM-INV",
        model="SIM",
        status=4,
        vendor_status=None,
        pac_w=pac_w,
        vdc_v=380.0,
        idc_a=1.0,
        total_wh=0.0,
        error=None,
        timestamp=datetime.now(timezone.utc),
    )


def _weather(ghi: float, cloud: float = 0.0, code: int | None = None, poa: float = None, expected_kw: float = None) -> WeatherEstimate:
    snap = WeatherSnapshot(
        timestamp=datetime.now(timezone.utc),
        source_series_time=datetime.now(timezone.utc),
        cloud_cover_pct=cloud,
        temp_c=0.0,
        wind_mps=0.0,
        ghi_wm2=ghi,
        dni_wm2=0.0,
        diffuse_wm2=ghi,
        weather_code=code,
        sun_azimuth_deg=100.0,
        sun_elevation_deg=10.0,
        provider="test",
        source_latitude=0.0,
        source_longitude=0.0,
        error=None,
    )
    inv = InverterExpectation(
        name="INV",
        expected_dc_kw=None,
        expected_ac_kw=expected_kw,
        poa_wm2=poa,
        cos_incidence=None,
        module_temp_c_est=None,
        temp_factor=None,
        array_kw_dc=1.0,
        ac_capacity_kw=1.0,
        dc_ac_derate=0.9,
        tilt_deg=20.0,
        azimuth_deg=160.0,
        albedo=0.15,
        noct_c=44.0,
        temp_coeff_per_c=-0.0026,
    )
    return WeatherEstimate(snapshot=snap, per_inverter={"INV": inv})


def _evaluate_with_weather(pac_w: float, weather_estimate: WeatherEstimate, cfg: HealthConfig) -> bool:
    evaluator = HealthEvaluator(cfg, LOG)
    snapshots = {"INV": _snapshot(pac_w)}
    capacity_map = {"INV": 1.0}
    thresholds = evaluator.derive_thresholds(snapshots.keys(), capacity_map)
    suppress = _compute_pac_alert_suppression(
        snapshots,
        weather_estimate,
        cfg,
        LOG,
        thresholds,
    )
    health = evaluator.evaluate(
        snapshots,
        capacity_by_name=capacity_map,
        thresholds=thresholds,
        pac_alert_suppression=suppress,
    )
    return health.system_ok and health.per_inverter["INV"].inverter_ok


def test_low_pac_suppressed_by_low_irradiance_floor():
    cfg = HealthConfig()
    weather_estimate = _weather(ghi=5.0, poa=5.0, expected_kw=0.0)
    # PAC (5 W) is below 1% floor (10 W for 1 kW), but low irradiance should suppress alert
    assert _evaluate_with_weather(pac_w=5.0, weather_estimate=weather_estimate, cfg=cfg)


def test_low_pac_suppressed_when_expected_below_floor():
    cfg = HealthConfig()
    # GHI above floor; expected AC is 5 W, below 1% floor → suppression
    weather_estimate = _weather(ghi=200.0, poa=50.0, expected_kw=0.005)
    assert _evaluate_with_weather(pac_w=5.0, weather_estimate=weather_estimate, cfg=cfg)


def test_low_pac_suppressed_by_precip_cloud_gate():
    cfg = HealthConfig()
    # Precip + 100% cloud should suppress PAC alert even with PAC below floor
    weather_estimate = _weather(ghi=200.0, cloud=100.0, code=73, poa=50.0, expected_kw=0.05)
    assert _evaluate_with_weather(pac_w=5.0, weather_estimate=weather_estimate, cfg=cfg)
