# solaredge_monitor/tests/test_weather_client.py

from datetime import datetime
from zoneinfo import ZoneInfo

from solaredge_monitor.config import InverterConfig, WeatherConfig
from solaredge_monitor.services.weather_client import WeatherClient
from solaredge_monitor.util.logging import get_logger, setup_logging


setup_logging(debug=False)
LOG = get_logger("weather-test")


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(200, self.payload)


def test_weather_client_computes_per_inverter_expectation():
    payload = {
        "timezone": "UTC",
        "current": {
            "time": "2024-01-01T10:00",
            "temperature_2m": 10.0,
            "cloud_cover": 50,
            "weather_code": 3,
        },
        "hourly": {
            "time": ["2024-01-01T10:00"],
            "shortwave_radiation": [600.0],
            "direct_normal_irradiance": [500.0],
            "diffuse_radiation": [100.0],
            "temperature_2m": [10.0],
            "cloud_cover": [50],
            "wind_speed_10m": [2.0],
        },
    }

    cfg = WeatherConfig(
        enabled=True,
        latitude=0.0,
        longitude=0.0,
        tilt_deg=20.0,
        azimuth_deg=180.0,
        albedo=0.2,
        array_kw_dc=18.0,
        ac_capacity_kw=10.0,
        dc_ac_derate=0.9,
        noct_c=45.0,
        temp_coeff_per_c=-0.0045,
    )
    invs = [InverterConfig(name="INV1", host="127.0.0.1")]
    now = datetime(2024, 1, 1, 10, 0, tzinfo=ZoneInfo("UTC"))

    client = WeatherClient(cfg, LOG, session=FakeSession(payload))
    estimate = client.fetch(now, invs, fallback_lat=cfg.latitude, fallback_lon=cfg.longitude)

    assert estimate is not None
    assert "INV1" in estimate.per_inverter
    inv_est = estimate.per_inverter["INV1"]
    assert inv_est.expected_ac_kw is not None
    assert inv_est.expected_ac_kw > 0
    # Should respect AC cap
    assert inv_est.expected_ac_kw <= cfg.ac_capacity_kw


def test_weather_disabled_short_circuits():
    cfg = WeatherConfig(enabled=False)
    client = WeatherClient(cfg, LOG, session=FakeSession({}))
    now = datetime.now(tz=ZoneInfo("UTC"))
    invs = [InverterConfig(name="INV", host="127.0.0.1")]

    assert client.fetch(now, invs, fallback_lat=0.0, fallback_lon=0.0) is None
