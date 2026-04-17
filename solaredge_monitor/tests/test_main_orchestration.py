from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.models.system_health import InverterHealth, SystemHealth
from solaredge_monitor.services.alert_logic import Alert
from solaredge_monitor.services.health_evaluator import Thresholds
from solaredge_monitor.services.se_api_client import CloudInverter
import solaredge_monitor.main as main_module


class DummyLog:
    def __init__(self, debug_enabled: bool = False):
        self.debug_enabled = debug_enabled
        self.messages: list[tuple[str, tuple]] = []

    def debug(self, msg, *args):
        self.messages.append((msg, args))

    def info(self, msg, *args):
        self.messages.append((msg, args))

    def warning(self, msg, *args):
        self.messages.append((msg, args))

    def isEnabledFor(self, level):
        return self.debug_enabled


class FakeConsoleLog:
    def __init__(self, log):
        self.log = log

    def setup(self):
        return self.log


class FakeStructuredLog:
    def __init__(self, *args, **kwargs):
        self.enabled = False

    def write(self, entry):
        raise AssertionError("structured logging should not be used in this test")


class FakeState:
    def __init__(self, *args, **kwargs):
        self.persist = kwargs.get("persist", True)
        self.path = kwargs.get("path")
        self.serials: dict[str, str] = {}
        self.latest_totals: list[tuple[str, object, float]] = []
        self.flush_called = False
        self.logged_run = None

    def update_inverter_serial(self, name, serial):
        self.serials[name] = serial

    def update_latest_total(self, serial, day, total_wh):
        self.latest_totals.append((serial, day, total_wh))

    def get_inverter_serial(self, name):
        return self.serials.get(name)

    def log_health_run(self, **kwargs):
        self.logged_run = kwargs

    def flush(self):
        self.flush_called = True


def _app_cfg(tmp_path, *, api_enabled: bool, skip_api_at_night: bool = False):
    inverter = SimpleNamespace(
        name="INV-A",
        host="127.0.0.1",
        port=1502,
        unit=1,
        expected_optimizers=12,
        ac_capacity_kw=4.0,
    )
    return SimpleNamespace(
        modbus=SimpleNamespace(
            inverters=[inverter],
            skip_modbus_at_night=True,
        ),
        pushover=SimpleNamespace(),
        healthchecks=SimpleNamespace(),
        health=SimpleNamespace(
            consecutive_health_alerts=1,
            consecutive_recovery_samples=1,
            identical_alert_gate_minutes=60,
            repeat_alert_interval_minutes=720,
            alert_irradiance_floor_wm2=30.0,
            precip_weather_codes=(61, 63),
            precip_cloud_cover_pct=100.0,
        ),
        daylight=SimpleNamespace(latitude=40.0, longitude=-74.0),
        solaredge_api=SimpleNamespace(enabled=api_enabled, skip_at_night=skip_api_at_night),
        state=SimpleNamespace(path=str(tmp_path / "state.db")),
        simulation=SimpleNamespace(
            scenario="sunset",
            simulated_time=None,
            as_mapping=lambda: {},
        ),
        retention=SimpleNamespace(snapshot_days=30, summary_days=90, vacuum_after_prune=False),
        weather=SimpleNamespace(enabled=False, log_path=None),
        logging=SimpleNamespace(
            console_level="INFO",
            console_quiet=False,
            debug_modules=[],
            structured_path=None,
            structured_enabled=False,
        ),
    )


def test_main_maintain_db_prunes_using_cli_and_config(monkeypatch, tmp_path):
    cfg = _app_cfg(tmp_path, api_enabled=False)
    log = DummyLog()
    prune_calls = []

    monkeypatch.setattr(main_module, "Config", SimpleNamespace(load=lambda path: cfg))
    monkeypatch.setattr(main_module, "ConsoleLog", lambda **kwargs: FakeConsoleLog(log))
    monkeypatch.setattr(main_module, "AppState", FakeState)
    monkeypatch.setattr(
        main_module,
        "state_maintenance",
        SimpleNamespace(prune=lambda state, snap_days, summary_days, vacuum: prune_calls.append((state, snap_days, summary_days, vacuum))),
    )
    monkeypatch.setattr(main_module, "StructuredLog", FakeStructuredLog)
    monkeypatch.setattr(main_module, "build_parser", main_module.build_parser)
    monkeypatch.setattr(main_module, "Path", main_module.Path)
    monkeypatch.setattr("sys.argv", ["prog", "--config", "x.conf", "maintain-db", "--snapshot-days", "11"])

    main_module.main()

    assert len(prune_calls) == 1
    _, snap_days, summary_days, vacuum = prune_calls[0]
    assert snap_days == 11
    assert summary_days == 90
    assert vacuum is False


def test_main_simulate_night_skips_modbus_and_notifications(monkeypatch, tmp_path):
    cfg = _app_cfg(tmp_path, api_enabled=False)
    log = DummyLog()
    notifier = SimpleNamespace(handle_alerts_calls=[], handle_alerts=lambda *args, **kwargs: notifier.handle_alerts_calls.append((args, kwargs)))
    state = FakeState(path=cfg.state.path, persist=False)

    class FakeDaylightPolicy:
        def __init__(self, *args, **kwargs):
            self.timezone = timezone.utc

        def get_info(self, now):
            return SimpleNamespace(
                skip_modbus=True,
                skip_cloud=True,
                in_grace_window=False,
                production_day_over=False,
                is_daylight=False,
                phase="night",
                sunrise=datetime(2024, 6, 2, 5, 30, tzinfo=timezone.utc),
            )

    class FakeSummaryService:
        def __init__(self, *args, **kwargs):
            pass

        def should_run(self, day, daylight_info):
            return False

    monkeypatch.setattr(main_module, "Config", SimpleNamespace(load=lambda path: cfg))
    monkeypatch.setattr(main_module, "ConsoleLog", lambda **kwargs: FakeConsoleLog(log))
    monkeypatch.setattr(main_module, "StructuredLog", FakeStructuredLog)
    monkeypatch.setattr(main_module, "AppState", lambda *args, **kwargs: state)
    monkeypatch.setattr(main_module, "NotificationManager", lambda *args, **kwargs: notifier)
    monkeypatch.setattr(main_module, "HealthEvaluator", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(main_module, "DaylightPolicy", FakeDaylightPolicy)
    monkeypatch.setattr(main_module, "SimulationReader", lambda *args, **kwargs: SimpleNamespace(read_all=lambda: []))
    monkeypatch.setattr(main_module, "SimulationAPIClient", lambda *args, **kwargs: SimpleNamespace(enabled=False))
    monkeypatch.setattr(main_module, "DailySummaryService", FakeSummaryService)
    monkeypatch.setattr(
        main_module,
        "AlertStateManager",
        lambda *args, **kwargs: SimpleNamespace(build_notification_batch=lambda **kwargs: ([], [], False)),
    )
    monkeypatch.setattr(main_module, "WeatherClient", lambda *args, **kwargs: SimpleNamespace(enabled=False))
    monkeypatch.setattr("sys.argv", ["prog", "--config", "x.conf", "--quiet", "simulate", "--scenario", "sunset"])

    main_module.main()

    assert notifier.handle_alerts_calls == []
    assert state.flush_called is True


def test_main_health_flow_reads_cloud_notifies_and_persists(monkeypatch, tmp_path):
    cfg = _app_cfg(tmp_path, api_enabled=True)
    log = DummyLog(debug_enabled=True)
    state = FakeState(path=cfg.state.path, persist=True)
    snapshot = InverterSnapshot(
        name="INV-A",
        serial="INV-A-SERIAL",
        model="SE",
        status=4,
        vendor_status=None,
        pac_w=2500.0,
        vdc_v=400.0,
        idc_a=6.0,
        total_wh=12000.0,
        error=None,
        timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
    )
    health = SystemHealth(
        system_ok=True,
        per_inverter={
            "INV-A": InverterHealth(
                name="INV-A",
                inverter_ok=True,
                reason=None,
                reading=snapshot,
                fault_code=None,
            )
        },
        reason=None,
        fault_code=None,
    )
    alert = Alert(
        inverter_name="INV-A",
        serial="INV-A-SERIAL",
        fault_code="synthetic_fault",
        message="Synthetic alert",
        status=4,
        pac_w=2500.0,
    )
    cloud_inventory = [
        CloudInverter(
            serial="INV-A-SERIAL",
            name="INV-A",
            status="Online",
            model="SE",
            connected_optimizers=12,
            raw={},
        )
    ]
    notifier_calls = []

    class FakeEvaluator:
        def __init__(self, *args, **kwargs):
            self.thresholds = Thresholds(
                low_pac_w={"INV-A": 40.0},
                low_light_peer_skip_w={"INV-A": 20.0},
                min_production_for_peer_check_w={"INV-A": 10.0},
            )
            self.optimizer_args = None

        def derive_thresholds(self, names, capacity_map):
            assert capacity_map == {"INV-A": 4.0}
            return self.thresholds

        def evaluate(self, *args, **kwargs):
            return health

        def update_with_optimizer_counts(self, health_obj, inverter_cfgs, serial_by_name, optimizer_counts_by_serial):
            self.optimizer_args = (health_obj, list(inverter_cfgs), serial_by_name, optimizer_counts_by_serial)
            return []

    evaluator = FakeEvaluator()

    class FakeDaylightPolicy:
        def __init__(self, *args, **kwargs):
            self.timezone = timezone.utc

        def get_info(self, now):
            return SimpleNamespace(
                skip_modbus=False,
                skip_cloud=False,
                in_grace_window=False,
                production_day_over=False,
                is_daylight=True,
                phase="day",
                sunrise=datetime(2024, 6, 1, 5, 30, tzinfo=timezone.utc),
                sunset=datetime(2024, 6, 1, 20, 30, tzinfo=timezone.utc),
                sunrise_grace_end=datetime(2024, 6, 1, 6, 0, tzinfo=timezone.utc),
                sunset_grace_start=datetime(2024, 6, 1, 19, 45, tzinfo=timezone.utc),
                production_over_at=datetime(2024, 6, 1, 22, 0, tzinfo=timezone.utc),
            )

    class FakeSEClient:
        enabled = True

        def fetch_inverters(self):
            return cloud_inventory

        def get_optimizer_counts(self, inventory=None):
            return {"INV-A-SERIAL": 12}

    class FakeSummaryService:
        def __init__(self, *args, **kwargs):
            pass

        def should_run(self, day, daylight_info):
            return False

    monkeypatch.setattr(main_module, "Config", SimpleNamespace(load=lambda path: cfg))
    monkeypatch.setattr(main_module, "ConsoleLog", lambda **kwargs: FakeConsoleLog(log))
    monkeypatch.setattr(main_module, "StructuredLog", FakeStructuredLog)
    monkeypatch.setattr(main_module, "AppState", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        main_module,
        "NotificationManager",
        lambda *args, **kwargs: SimpleNamespace(
            handle_alerts=lambda alerts, recoveries=None, health=None, has_active_health_incident=False: notifier_calls.append((alerts, recoveries, health))
        ),
    )
    monkeypatch.setattr(main_module, "HealthEvaluator", lambda *args, **kwargs: evaluator)
    monkeypatch.setattr(main_module, "DaylightPolicy", FakeDaylightPolicy)
    monkeypatch.setattr(main_module, "ModbusReader", lambda *args, **kwargs: SimpleNamespace(read_all=lambda: {"INV-A": snapshot}))
    monkeypatch.setattr(main_module, "SolarEdgeAPIClient", lambda *args, **kwargs: FakeSEClient())
    monkeypatch.setattr(main_module, "DailySummaryService", FakeSummaryService)
    monkeypatch.setattr(
        main_module,
        "AlertStateManager",
        lambda *args, **kwargs: SimpleNamespace(build_notification_batch=lambda **kwargs: ([alert], [], False)),
    )
    monkeypatch.setattr(main_module, "WeatherClient", lambda *args, **kwargs: SimpleNamespace(enabled=False))
    monkeypatch.setattr("sys.argv", ["prog", "--config", "x.conf", "--quiet", "health"])

    main_module.main()

    assert notifier_calls == [([alert], [], health)]
    assert state.logged_run is not None
    assert state.logged_run["snapshots"] == {"INV-A": snapshot}
    assert state.serials["INV-A"] == "INV-A-SERIAL"
    assert state.flush_called is True
    assert evaluator.optimizer_args is not None
    assert evaluator.optimizer_args[2] == {"INV-A": "INV-A-SERIAL"}
    assert evaluator.optimizer_args[3] == {"INV-A-SERIAL": 12}


def test_main_health_flow_passes_unhealthy_state_when_alerts_suppressed(monkeypatch, tmp_path):
    cfg = _app_cfg(tmp_path, api_enabled=False)
    log = DummyLog()
    state = FakeState(path=cfg.state.path, persist=True)
    snapshot = InverterSnapshot(
        name="INV-A",
        serial="INV-A-SERIAL",
        model="SE",
        status=4,
        vendor_status=None,
        pac_w=0.0,
        vdc_v=0.0,
        idc_a=0.0,
        total_wh=12000.0,
        error=None,
        timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
    )
    health = SystemHealth(
        system_ok=False,
        per_inverter={
            "INV-A": InverterHealth(
                name="INV-A",
                inverter_ok=False,
                reason="No Modbus data (offline?)",
                reading=None,
                fault_code="optimizer_mismatch",
            )
        },
        reason="INV-A: No Modbus data (offline?)",
        fault_code="inverter_faults",
    )
    notifier_calls = []

    class FakeEvaluator:
        def derive_thresholds(self, names, capacity_map):
            return Thresholds(
                low_pac_w={"INV-A": 40.0},
                low_light_peer_skip_w={"INV-A": 20.0},
                min_production_for_peer_check_w={"INV-A": 10.0},
            )

        def evaluate(self, *args, **kwargs):
            return health

        def update_with_optimizer_counts(self, *args, **kwargs):
            return []

    class FakeDaylightPolicy:
        def __init__(self, *args, **kwargs):
            self.timezone = timezone.utc

        def get_info(self, now):
            return SimpleNamespace(
                skip_modbus=False,
                skip_cloud=False,
                in_grace_window=False,
                production_day_over=False,
                is_daylight=True,
                phase="day",
                sunrise=datetime(2024, 6, 1, 5, 30, tzinfo=timezone.utc),
                sunset=datetime(2024, 6, 1, 20, 30, tzinfo=timezone.utc),
                sunrise_grace_end=datetime(2024, 6, 1, 6, 0, tzinfo=timezone.utc),
                sunset_grace_start=datetime(2024, 6, 1, 19, 45, tzinfo=timezone.utc),
                production_over_at=datetime(2024, 6, 1, 22, 0, tzinfo=timezone.utc),
            )

    class FakeSummaryService:
        def __init__(self, *args, **kwargs):
            pass

        def should_run(self, day, daylight_info):
            return False

    monkeypatch.setattr(main_module, "Config", SimpleNamespace(load=lambda path: cfg))
    monkeypatch.setattr(main_module, "ConsoleLog", lambda **kwargs: FakeConsoleLog(log))
    monkeypatch.setattr(main_module, "StructuredLog", FakeStructuredLog)
    monkeypatch.setattr(main_module, "AppState", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        main_module,
        "NotificationManager",
        lambda *args, **kwargs: SimpleNamespace(
            handle_alerts=lambda alerts, recoveries=None, health=None, has_active_health_incident=False: notifier_calls.append((alerts, recoveries, health))
        ),
    )
    monkeypatch.setattr(main_module, "HealthEvaluator", lambda *args, **kwargs: FakeEvaluator())
    monkeypatch.setattr(main_module, "DaylightPolicy", FakeDaylightPolicy)
    monkeypatch.setattr(main_module, "ModbusReader", lambda *args, **kwargs: SimpleNamespace(read_all=lambda: {"INV-A": snapshot}))
    monkeypatch.setattr(main_module, "SolarEdgeAPIClient", lambda *args, **kwargs: SimpleNamespace(enabled=False))
    monkeypatch.setattr(main_module, "DailySummaryService", FakeSummaryService)
    monkeypatch.setattr(
        main_module,
        "AlertStateManager",
        lambda *args, **kwargs: SimpleNamespace(build_notification_batch=lambda **kwargs: ([], [], False)),
    )
    monkeypatch.setattr(main_module, "WeatherClient", lambda *args, **kwargs: SimpleNamespace(enabled=False))
    monkeypatch.setattr("sys.argv", ["prog", "--config", "x.conf", "--quiet", "health"])

    main_module.main()

    assert notifier_calls == [([], [], health)]
    assert state.logged_run is not None
    assert state.flush_called is True


def test_main_health_flow_uses_cached_serials_for_optimizer_lookup_when_modbus_is_offline(monkeypatch, tmp_path):
    cfg = _app_cfg(tmp_path, api_enabled=True)
    log = DummyLog()
    state = FakeState(path=cfg.state.path, persist=True)
    state.serials["INV-A"] = "INV-A-SERIAL"
    health = SystemHealth(
        system_ok=False,
        per_inverter={
            "INV-A": InverterHealth(
                name="INV-A",
                inverter_ok=False,
                reason="No Modbus data (offline?)",
                reading=None,
                fault_code="offline",
            )
        },
        reason="INV-A: No Modbus data (offline?)",
        fault_code="inverter_faults",
    )
    cloud_inventory = [
        CloudInverter(
            serial="INV-A-SERIAL-CF",
            name="Inverter 1",
            status="Online",
            model="SE",
            connected_optimizers=12,
            raw={},
        )
    ]

    class FakeEvaluator:
        def __init__(self, *args, **kwargs):
            self.optimizer_args = None

        def derive_thresholds(self, names, capacity_map):
            return Thresholds(
                low_pac_w={},
                low_light_peer_skip_w={},
                min_production_for_peer_check_w={},
            )

        def evaluate(self, *args, **kwargs):
            return health

        def update_with_optimizer_counts(self, health_obj, inverter_cfgs, serial_by_name, optimizer_counts_by_serial):
            self.optimizer_args = (health_obj, list(inverter_cfgs), serial_by_name, optimizer_counts_by_serial)
            return []

    evaluator = FakeEvaluator()

    class FakeDaylightPolicy:
        def __init__(self, *args, **kwargs):
            self.timezone = timezone.utc

        def get_info(self, now):
            return SimpleNamespace(
                skip_modbus=False,
                skip_cloud=False,
                in_grace_window=False,
                production_day_over=False,
                is_daylight=True,
                phase="day",
                sunrise=datetime(2024, 6, 1, 5, 30, tzinfo=timezone.utc),
                sunset=datetime(2024, 6, 1, 20, 30, tzinfo=timezone.utc),
                sunrise_grace_end=datetime(2024, 6, 1, 6, 0, tzinfo=timezone.utc),
                sunset_grace_start=datetime(2024, 6, 1, 19, 45, tzinfo=timezone.utc),
                production_over_at=datetime(2024, 6, 1, 22, 0, tzinfo=timezone.utc),
            )

    class FakeSEClient:
        enabled = True

        def fetch_inverters(self):
            return cloud_inventory

        def get_optimizer_counts(self, inventory=None):
            return {
                "INV-A-SERIAL-CF": 12,
                "INV-A-SERIAL": 12,
            }

    class FakeSummaryService:
        def __init__(self, *args, **kwargs):
            pass

        def should_run(self, day, daylight_info):
            return False

    monkeypatch.setattr(main_module, "Config", SimpleNamespace(load=lambda path: cfg))
    monkeypatch.setattr(main_module, "ConsoleLog", lambda **kwargs: FakeConsoleLog(log))
    monkeypatch.setattr(main_module, "StructuredLog", FakeStructuredLog)
    monkeypatch.setattr(main_module, "AppState", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        main_module,
        "NotificationManager",
        lambda *args, **kwargs: SimpleNamespace(handle_alerts=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(main_module, "HealthEvaluator", lambda *args, **kwargs: evaluator)
    monkeypatch.setattr(main_module, "DaylightPolicy", FakeDaylightPolicy)
    monkeypatch.setattr(main_module, "ModbusReader", lambda *args, **kwargs: SimpleNamespace(read_all=lambda: {"INV-A": None}))
    monkeypatch.setattr(main_module, "SolarEdgeAPIClient", lambda *args, **kwargs: FakeSEClient())
    monkeypatch.setattr(main_module, "DailySummaryService", FakeSummaryService)
    monkeypatch.setattr(
        main_module,
        "AlertStateManager",
        lambda *args, **kwargs: SimpleNamespace(build_notification_batch=lambda **kwargs: ([], [], False)),
    )
    monkeypatch.setattr(main_module, "WeatherClient", lambda *args, **kwargs: SimpleNamespace(enabled=False))
    monkeypatch.setattr("sys.argv", ["prog", "--config", "x.conf", "--quiet", "health"])

    main_module.main()

    assert evaluator.optimizer_args is not None
    assert evaluator.optimizer_args[2]["INV-A"] == "INV-A-SERIAL"
    assert evaluator.optimizer_args[3] == {"INV-A-SERIAL-CF": 12, "INV-A-SERIAL": 12}
