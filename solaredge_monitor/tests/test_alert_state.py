from datetime import datetime
from types import SimpleNamespace

from solaredge_monitor.services.alert_state import AlertStateManager
from solaredge_monitor.models.system_health import SystemHealth, InverterHealth
from solaredge_monitor.models.inverter import InverterSnapshot


def _health(system_ok=True):
    snapshot = InverterSnapshot(
        name="INV-A",
        serial="SER123",
        model="M",
        status=4,
        vendor_status=None,
        pac_w=1000,
        vdc_v=400,
        idc_a=3,
        error=None,
        timestamp=datetime.now(),
    )
    inverter_health = InverterHealth(
        name="INV-A",
        inverter_ok=system_ok,
        reason=None if system_ok else "Fault",
        reading=snapshot,
    )
    return SystemHealth(system_ok=system_ok, per_inverter={"INV-A": inverter_health}, reason=None)


def test_alert_manager_uses_health_alerts():
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))
    health = _health(system_ok=False)

    alerts = mgr.build_alerts(
        now=datetime.now(),
        health=health,
        optimizer_mismatches=[],
    )

    assert alerts
    assert alerts[0].inverter_name == "INV-A"


def test_alert_manager_handles_optimizer_mismatches_without_health():
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))

    mismatches = [("INV-A", 10, 2)]
    alerts = mgr.build_alerts(
        now=datetime.now(),
        health=None,
        optimizer_mismatches=mismatches,
    )

    assert alerts
    assert "Optimizer count mismatch" in alerts[0].message


def test_alert_manager_includes_extra_messages():
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))

    alerts = mgr.build_alerts(
        now=datetime.now(),
        health=None,
        optimizer_mismatches=[],
        extra_messages=["Daily summary failed"],
    )

    assert len(alerts) == 1
    assert alerts[0].message == "Daily summary failed"
