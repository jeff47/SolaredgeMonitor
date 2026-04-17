from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from solaredge_monitor.config import HealthchecksConfig, PushoverConfig
from solaredge_monitor.logging import ConsoleLog, get_logger
from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.models.system_health import InverterHealth, SystemHealth
from solaredge_monitor.models.weather import InverterExpectation, WeatherEstimate, WeatherSnapshot
from solaredge_monitor.services.alert_logic import Alert
from solaredge_monitor.services.alert_state import RecoveryNotification
from solaredge_monitor.services.notification_manager import NotificationManager
from solaredge_monitor.services.notifiers.healthchecks import HealthchecksNotifier
from solaredge_monitor.services.notifiers.pushover import PushoverNotifier
from solaredge_monitor.services.output_formatter import emit_human, emit_json
from solaredge_monitor.services.se_api_client import CloudInverter


ConsoleLog(level="INFO", quiet=True).setup()
LOG = get_logger("notifications-output-test")


def _snapshot(name: str, *, status: int = 4, pac_w: float | None = 2500.0, error: str | None = None) -> InverterSnapshot:
    return InverterSnapshot(
        name=name,
        serial=f"{name}-SERIAL",
        model="SE",
        status=status,
        vendor_status=None,
        pac_w=pac_w,
        vdc_v=400.0,
        idc_a=6.0,
        total_wh=12345.0,
        error=error,
        timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
    )


def _weather() -> WeatherEstimate:
    snap = WeatherSnapshot(
        timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        source_series_time=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        cloud_cover_pct=25.0,
        temp_c=27.0,
        wind_mps=3.2,
        ghi_wm2=800.0,
        dni_wm2=600.0,
        diffuse_wm2=150.0,
        weather_code=1,
        sun_azimuth_deg=180.0,
        sun_elevation_deg=55.0,
        provider="open-meteo",
        source_latitude=40.0,
        source_longitude=-74.0,
    )
    inv = InverterExpectation(
        name="INV-A",
        expected_dc_kw=3.1,
        expected_ac_kw=2.8,
        poa_wm2=900.0,
        cos_incidence=0.95,
        module_temp_c_est=42.0,
        temp_factor=0.92,
        array_kw_dc=3.5,
        ac_capacity_kw=3.0,
        dc_ac_derate=0.9,
        tilt_deg=20.0,
        azimuth_deg=180.0,
        albedo=0.2,
        noct_c=45.0,
        temp_coeff_per_c=-0.0045,
    )
    return WeatherEstimate(snapshot=snap, per_inverter={"INV-A": inv})


def test_notification_manager_routes_success_and_failure():
    manager = NotificationManager(PushoverConfig(), HealthchecksConfig(), LOG)
    pushover_calls: list[tuple[str, object]] = []
    healthchecks_calls: list[tuple[str, str]] = []

    manager.pushover = SimpleNamespace(
        send_alerts=lambda alerts, health=None: pushover_calls.append(("alerts", list(alerts))),
        send_test=lambda: pushover_calls.append(("test", None)),
        send_message=lambda title, message: pushover_calls.append((title, message)),
    )
    manager.healthchecks = SimpleNamespace(
        ping_success=lambda message="": healthchecks_calls.append(("success", message)),
        ping_failure=lambda message="": healthchecks_calls.append(("failure", message)),
        send_test=lambda: healthchecks_calls.append(("test", "")),
    )

    healthy = SystemHealth(system_ok=True, per_inverter={}, reason=None, fault_code=None)
    manager.handle_alerts([], health=healthy)
    alert = Alert(
        inverter_name="INV-A",
        serial="INV-A-SERIAL",
        fault_code="fault_state:7",
        message="Fault state",
        status=7,
        pac_w=0.0,
    )
    manager.handle_alerts([alert])
    manager.send_daily_summary("summary body", 3200.0, 4000.0)

    assert healthchecks_calls[0] == ("success", "system ok")
    assert pushover_calls[0] == ("alerts", [alert])
    assert healthchecks_calls[1] == ("failure", "INV-A:7")
    assert pushover_calls[1] == ("SolarEdge Daily Production: 3.20 kWh", "summary body")


def test_notification_manager_sends_recovery_then_success_ping():
    manager = NotificationManager(PushoverConfig(), HealthchecksConfig(), LOG)
    pushover_calls: list[tuple[str, object]] = []
    healthchecks_calls: list[tuple[str, str]] = []

    manager.pushover = SimpleNamespace(
        send_alerts=lambda alerts, health=None: pushover_calls.append(("alerts", list(alerts))),
        send_recoveries=lambda recoveries: pushover_calls.append(("recoveries", list(recoveries))),
        send_test=lambda: None,
        send_message=lambda title, message: None,
    )
    manager.healthchecks = SimpleNamespace(
        ping_success=lambda message="": healthchecks_calls.append(("success", message)),
        ping_failure=lambda message="": healthchecks_calls.append(("failure", message)),
        send_test=lambda: None,
    )

    recovery = RecoveryNotification(
        inverter_name="INV-A",
        serial="INV-A-SERIAL",
        fault_code="offline",
        message="Recovered after 1:00:00: No Modbus data (offline?)",
        resolved_at=datetime(2024, 6, 1, 13, 0, tzinfo=timezone.utc),
        first_seen=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
    )
    healthy = SystemHealth(system_ok=True, per_inverter={}, reason=None, fault_code=None)
    manager.handle_alerts([], recoveries=[recovery], health=healthy)

    assert pushover_calls == [("recoveries", [recovery])]
    assert healthchecks_calls == [("success", "system ok")]


def test_notification_manager_sends_failure_ping_for_suppressed_persistent_fault():
    manager = NotificationManager(PushoverConfig(), HealthchecksConfig(), LOG)
    pushover_calls: list[tuple[str, object]] = []
    healthchecks_calls: list[tuple[str, str]] = []

    manager.pushover = SimpleNamespace(
        send_alerts=lambda alerts, health=None: pushover_calls.append(("alerts", list(alerts))),
        send_recoveries=lambda recoveries: pushover_calls.append(("recoveries", list(recoveries))),
        send_test=lambda: None,
        send_message=lambda title, message: None,
    )
    manager.healthchecks = SimpleNamespace(
        ping_success=lambda message="": healthchecks_calls.append(("success", message)),
        ping_failure=lambda message="": healthchecks_calls.append(("failure", message)),
        send_test=lambda: None,
    )

    health = SystemHealth(
        system_ok=False,
        per_inverter={
            "SE10000H": InverterHealth(
                name="SE10000H",
                inverter_ok=False,
                reason="No Modbus data (offline?)",
                reading=None,
                fault_code="optimizer_mismatch",
            )
        },
        reason="SE10000H: No Modbus data (offline?)",
        fault_code="inverter_faults",
    )

    manager.handle_alerts([], health=health, has_active_health_incident=True)

    assert pushover_calls == []
    assert healthchecks_calls == [("failure", "SE10000H: No Modbus data (offline?)")]


def test_pushover_formats_alert_with_baseline(monkeypatch):
    posted: list[tuple[str, str]] = []
    notifier = PushoverNotifier(
        PushoverConfig(token="t", user="u", enabled=True),
        LOG,
    )
    monkeypatch.setattr(notifier, "_post", lambda title, message, priority=0: posted.append((title, message)) or True)

    failing = InverterHealth(
        name="INV-A",
        inverter_ok=False,
        reason="Low output",
        reading=_snapshot("INV-A", status=4, pac_w=100.0),
        fault_code="peer_mismatch",
    )
    healthy = InverterHealth(
        name="INV-B",
        inverter_ok=True,
        reason=None,
        reading=_snapshot("INV-B", status=4, pac_w=3100.0),
        fault_code=None,
    )
    health = SystemHealth(
        system_ok=False,
        per_inverter={"INV-A": failing, "INV-B": healthy},
        reason="INV-A: Low output",
        fault_code="inverter_faults",
    )

    notifier.send_alerts(
        [Alert(inverter_name="INV-A", serial="INV-A-SERIAL", fault_code="peer_mismatch", message="Low output", status=4, pac_w=100.0)],
        health=health,
    )

    assert posted
    title, message = posted[0]
    assert title == "SolarEdge Alert"
    assert "INV-A: status=4, PAC=100 W" in message
    assert "Reason: Low output" in message
    assert "Baseline INV-B: status=4, PAC=3100 W" in message


def test_healthchecks_notifier_encodes_failure_message(monkeypatch):
    opened: list[str] = []
    notifier = HealthchecksNotifier(
        HealthchecksConfig(ping_url="https://hc.example/ping/abc", enabled=True),
        LOG,
    )

    def fake_urlopen(url, timeout=10):
        opened.append(url)
        return object()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    notifier.ping_failure("x" * 300)

    assert opened
    parsed = urlparse(opened[0])
    assert parsed.path.endswith("/ping/abc/fail")
    assert len(parse_qs(parsed.query)["msg"][0]) == 200


def test_no_failure_ping_when_health_failing_but_no_active_incident():
    """Health failing but below consecutive threshold: should send success ping, not failure."""
    manager = NotificationManager(PushoverConfig(), HealthchecksConfig(), LOG)
    healthchecks_calls: list[tuple[str, str]] = []

    manager.pushover = SimpleNamespace(
        send_alerts=lambda alerts, health=None: None,
        send_recoveries=lambda recoveries: None,
        send_message=lambda title, message: None,
    )
    manager.healthchecks = SimpleNamespace(
        ping_success=lambda message="": healthchecks_calls.append(("success", message)),
        ping_failure=lambda message="": healthchecks_calls.append(("failure", message)),
    )

    health = SystemHealth(
        system_ok=False,
        per_inverter={},
        reason="low_pac",
        fault_code="low_pac",
    )
    manager.handle_alerts([], health=health, has_active_health_incident=False)

    assert healthchecks_calls == [("success", "system ok")], "Should ping success when no active incident yet"


def test_handle_alerts_no_ping_when_health_is_none():
    """When health=None (all inverters unreachable), no Healthchecks ping should be sent
    — not even a false success ping."""
    manager = NotificationManager(PushoverConfig(), HealthchecksConfig(), LOG)
    healthchecks_calls: list[tuple[str, str]] = []

    manager.pushover = SimpleNamespace(
        send_alerts=lambda alerts, health=None: None,
        send_recoveries=lambda recoveries: None,
        send_message=lambda title, message: None,
    )
    manager.healthchecks = SimpleNamespace(
        ping_success=lambda message="": healthchecks_calls.append(("success", message)),
        ping_failure=lambda message="": healthchecks_calls.append(("failure", message)),
    )

    manager.handle_alerts([], health=None)

    assert healthchecks_calls == [], "Should not ping when health is unknown"


def test_emit_json_includes_weather_and_offline_record(capsys):
    snapshot_items = [
        ("INV-A", _snapshot("INV-A", pac_w=2800.0)),
        ("INV-B", None),
    ]
    cloud = {
        "INV-A-SERIAL": CloudInverter(
            serial="INV-A-SERIAL",
            name="INV-A",
            status="Online",
            model="SE",
            connected_optimizers=12,
            raw={},
        )
    }

    emit_json(snapshot_items, cloud, weather_estimate=_weather())
    out = capsys.readouterr().out

    assert '"name": "INV-A"' in out
    assert '"cloud_status": "Online"' in out
    assert '"optimizers": 12' in out
    assert '"name": "INV-B"' in out
    assert '"error": "No Modbus data"' in out
    assert '"weather"' in out
    assert '"expected_ac_kw": 2.8' in out


def test_emit_human_prints_weather_cloud_and_error_lines(capsys):
    snapshot_items = [
        ("INV-A", _snapshot("INV-A", pac_w=2800.0)),
        ("INV-B", _snapshot("INV-B", error="read failed")),
        ("INV-C", None),
    ]
    cloud = {
        "INV-A-SERIAL": CloudInverter(
            serial="INV-A-SERIAL",
            name="INV-A",
            status="Online",
            model="SE",
            connected_optimizers=12,
            raw={},
        )
    }

    emit_human(snapshot_items, cloud, weather_estimate=_weather())
    out = capsys.readouterr().out

    assert "Weather (open-meteo)" in out
    assert "[INV-A] expected=2.80kW actual=2.80kW poa=900W/m2" in out
    assert "[INV-A] PAC=2800W" in out
    assert "cloud=Online optimizers=12" in out
    assert "[INV-B] ERROR: read failed" in out
    assert "[INV-C] OFFLINE: no Modbus data" in out
