from datetime import datetime, timedelta
from types import SimpleNamespace

from solaredge_monitor.services.alert_state import AlertStateManager
from solaredge_monitor.services.alert_logic import evaluate_alerts
from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.models.system_health import SystemHealth, InverterHealth
from solaredge_monitor.models.inverter import InverterSnapshot


def _alerts(mgr, **kwargs):
    alerts, recoveries, _ = mgr.build_notification_batch(**kwargs)
    assert recoveries == []
    return alerts


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
        total_wh=0.0,
        error=None,
        timestamp=datetime.now(),
    )
    inverter_health = InverterHealth(
        name="INV-A",
        inverter_ok=system_ok,
        reason=None if system_ok else "Fault",
        reading=snapshot,
        fault_code=None if system_ok else "fault_state:4",
    )
    return SystemHealth(system_ok=system_ok, per_inverter={"INV-A": inverter_health}, reason=None, fault_code=None)


def test_alert_manager_uses_health_alerts():
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))
    health = _health(system_ok=False)

    alerts = _alerts(
        mgr,
        now=datetime.now(),
        health=health,
        optimizer_mismatches=[],
    )

    assert alerts
    assert alerts[0].inverter_name == "INV-A"


def test_alert_manager_handles_optimizer_mismatches_without_health():
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))

    mismatches = [("INV-A", 10, 2)]
    alerts = _alerts(
        mgr,
        now=datetime.now(),
        health=None,
        optimizer_mismatches=mismatches,
    )

    assert alerts
    assert "Optimizer count mismatch" in alerts[0].message


def test_optimizer_mismatch_emitted_alongside_health_fault():
    """Optimizer mismatches must fire even when health evaluation succeeds.
    Previously they were silently dropped whenever health was not None."""
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))
    unhealthy = _health(system_ok=False)

    alerts = _alerts(
        mgr,
        now=datetime.now(),
        health=unhealthy,
        optimizer_mismatches=[("INV-A", 10, 2)],
    )

    fault_codes = {a.fault_code for a in alerts}
    assert any("fault_state" in fc for fc in fault_codes), "health fault not emitted"
    assert "optimizer_mismatch" in fault_codes, "optimizer mismatch silently dropped"


def test_alert_manager_includes_extra_messages():
    mgr = AlertStateManager(log=SimpleNamespace(debug=lambda *args, **kwargs: None))

    alerts = _alerts(
        mgr,
        now=datetime.now(),
        health=None,
        optimizer_mismatches=[],
        extra_messages=["Daily summary failed"],
    )

    assert len(alerts) == 1
    assert alerts[0].message == "Daily summary failed"


def test_consecutive_alerts_gate_and_reset():
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
        consecutive_required=2,
    )

    unhealthy = _health(system_ok=False)
    first = _alerts(
        mgr,
        now=datetime.now(),
        health=unhealthy,
        optimizer_mismatches=[],
    )
    assert first == []  # first failure suppressed

    second = _alerts(
        mgr,
        now=datetime.now(),
        health=unhealthy,
        optimizer_mismatches=[],
    )
    assert len(second) == 1  # second consecutive failure emits alert

    healthy = _health(system_ok=True)
    cleared, recoveries, _ = mgr.build_notification_batch(
        now=datetime.now(),
        health=healthy,
        optimizer_mismatches=[],
    )
    assert cleared == []
    assert len(recoveries) == 1

    # After reset, a new failure should again require two runs
    third = _alerts(
        mgr,
        now=datetime.now(),
        health=unhealthy,
        optimizer_mismatches=[],
    )
    assert third == []


def test_recovery_gate_requires_consecutive_healthy_samples():
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
        consecutive_required=2,
        consecutive_recovery_required=3,
    )
    t0 = datetime(2024, 6, 1, 12, 0, 0)

    unhealthy = _health(system_ok=False)
    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0,
        health=unhealthy,
        optimizer_mismatches=[],
    )
    assert alerts == []
    assert recoveries == []

    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=5),
        health=unhealthy,
        optimizer_mismatches=[],
    )
    assert len(alerts) == 1
    assert recoveries == []

    healthy = _health(system_ok=True)
    for minutes in (10, 15):
        alerts, recoveries, _ = mgr.build_notification_batch(
            now=t0 + timedelta(minutes=minutes),
            health=healthy,
            optimizer_mismatches=[],
        )
        assert alerts == []
        assert recoveries == []

    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=20),
        health=healthy,
        optimizer_mismatches=[],
    )
    assert alerts == []
    assert len(recoveries) == 1


def test_identical_alerts_are_suppressed_then_reminded():
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
        identical_alert_gate_minutes=60,
        repeat_alert_interval_minutes=12 * 60,
    )
    unhealthy = _health(system_ok=False)
    t0 = datetime(2024, 6, 1, 12, 0, 0)

    first = _alerts(mgr, now=t0, health=unhealthy, optimizer_mismatches=[])
    second = _alerts(mgr, now=t0 + timedelta(minutes=5), health=unhealthy, optimizer_mismatches=[])
    third = _alerts(mgr, now=t0 + timedelta(hours=1), health=unhealthy, optimizer_mismatches=[])
    fourth = _alerts(mgr, now=t0 + timedelta(hours=2), health=unhealthy, optimizer_mismatches=[])
    fifth = _alerts(mgr, now=t0 + timedelta(hours=13), health=unhealthy, optimizer_mismatches=[])

    assert len(first) == 1
    assert second == []
    assert len(third) == 1
    assert fourth == []
    assert len(fifth) == 1


def test_fault_change_emits_immediately_and_recovery_is_reported():
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
    )
    t0 = datetime(2024, 6, 1, 12, 0, 0)

    first_health = _health(system_ok=False)
    first_health.per_inverter["INV-A"].reason = "No Modbus data (offline?)"
    first_health.per_inverter["INV-A"].reading = None
    first_health.per_inverter["INV-A"].fault_code = "offline"
    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0,
        health=first_health,
        optimizer_mismatches=[],
    )
    assert len(alerts) == 1
    assert recoveries == []

    changed_health = _health(system_ok=False)
    changed_health.per_inverter["INV-A"].reason = "Low DC voltage Vdc=40.0 V (<50.0 V threshold)"
    changed_health.per_inverter["INV-A"].fault_code = "low_vdc"
    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=10),
        health=changed_health,
        optimizer_mismatches=[],
    )
    assert len(alerts) == 1
    assert recoveries == []

    healthy = _health(system_ok=True)
    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=20),
        health=healthy,
        optimizer_mismatches=[],
    )
    assert alerts == []
    assert len(recoveries) == 1
    assert recoveries[0].inverter_name == "INV-A"
    assert "Recovered" in recoveries[0].message


def test_optimizer_mismatch_resolves_when_source_evaluated_empty():
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
    )
    t0 = datetime(2024, 6, 1, 12, 0, 0)

    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0,
        health=None,
        optimizer_mismatches=[("INV-A", 10, 2)],
    )
    assert len(alerts) == 1
    assert recoveries == []

    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=5),
        health=None,
        optimizer_mismatches=[],
    )
    assert alerts == []
    assert len(recoveries) == 1
    assert recoveries[0].fault_code == "optimizer_mismatch"


def test_system_message_resolves_when_source_evaluated_empty():
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
    )
    t0 = datetime(2024, 6, 1, 12, 0, 0)

    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0,
        health=None,
        optimizer_mismatches=None,
        extra_messages=["Daily summary failed"],
    )
    assert len(alerts) == 1
    assert recoveries == []

    alerts, recoveries, _ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=5),
        health=None,
        optimizer_mismatches=None,
        extra_messages=[],
    )
    assert alerts == []
    assert len(recoveries) == 1
    assert recoveries[0].fault_code == "system_message"


def test_evaluate_alerts_system_level_fault_with_no_bad_inverters():
    """When system_ok=False but all individual inverters are OK, a SYSTEM-level alert is emitted."""
    health = SystemHealth(
        system_ok=False,
        per_inverter={
            "INV-A": InverterHealth(name="INV-A", inverter_ok=True, reason=None, reading=None, fault_code=None),
        },
        reason="Aggregate system failure",
        fault_code="system_failure",
    )

    alerts = evaluate_alerts(health)

    assert len(alerts) == 1
    assert alerts[0].inverter_name == "SYSTEM"
    assert alerts[0].fault_code == "system_failure"
    assert "Aggregate system failure" in alerts[0].message


def test_corrupted_last_alerted_causes_immediate_re_emit():
    """A corrupted last_alerted timestamp in state should be treated as never-alerted, re-emitting immediately."""
    state = AppState(persist=False)
    mgr = AlertStateManager(
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
        state=state,
        identical_alert_gate_minutes=60,
    )
    t0 = datetime(2024, 6, 1, 12, 0, 0)
    unhealthy = _health(system_ok=False)

    # First run — establishes the incident with a valid last_alerted
    alerts, _, __ = mgr.build_notification_batch(now=t0, health=unhealthy, optimizer_mismatches=[])
    assert len(alerts) == 1

    # Corrupt the last_alerted field directly in state
    incidents = state.get("open_alert_incidents", {})
    incidents["INV-A"]["last_alerted"] = "not-a-valid-datetime"
    state.set("open_alert_incidents", incidents)

    # Second run 5 minutes later — normally suppressed by the 60-min gate,
    # but corruption causes _parse_dt to return None, which re-emits immediately
    alerts, _, __ = mgr.build_notification_batch(
        now=t0 + timedelta(minutes=5), health=unhealthy, optimizer_mismatches=[]
    )
    assert len(alerts) == 1
