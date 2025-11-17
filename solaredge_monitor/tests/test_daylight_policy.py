# solaredge_monitor/tests/test_daylight_policy.py

from datetime import datetime, timezone

from solaredge_monitor.config import DaylightConfig
from solaredge_monitor.services.daylight_policy import DaylightPolicy
from solaredge_monitor.util.logging import setup_logging, get_logger


setup_logging(debug=False)
LOG = get_logger("daylight-test")


def _policy(**overrides):
    cfg = DaylightConfig(
        timezone="UTC",
        latitude=None,
        longitude=None,
        static_sunrise="06:00",
        static_sunset="18:00",
        sunrise_grace_minutes=30,
        sunset_grace_minutes=45,
        summary_delay_minutes=60,
        skip_modbus_at_night=True,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return DaylightPolicy(cfg, LOG)


def test_nighttime_skips_modbus():
    policy = _policy()
    now = datetime(2024, 6, 1, 2, 0, tzinfo=timezone.utc)
    info = policy.get_info(now)
    assert info.phase == "NIGHT"
    assert info.skip_modbus is True


def test_sunrise_grace_window_flag():
    policy = _policy()
    now = datetime(2024, 6, 1, 6, 10, tzinfo=timezone.utc)
    info = policy.get_info(now)
    assert info.phase == "SUNRISE_GRACE"
    assert info.in_grace_window
    assert info.skip_modbus is False


def test_midday_allows_checks():
    policy = _policy()
    now = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
    info = policy.get_info(now)
    assert info.phase == "DAY"
    assert not info.in_grace_window
    assert info.is_daylight


def test_sunset_grace_and_production_over():
    policy = _policy(summary_delay_minutes=30)
    now = datetime(2024, 6, 1, 17, 30, tzinfo=timezone.utc)
    info = policy.get_info(now)
    assert info.phase == "SUNSET_GRACE"
    assert info.in_grace_window

    later = datetime(2024, 6, 1, 19, 0, tzinfo=timezone.utc)
    later_info = policy.get_info(later)
    assert later_info.production_day_over
