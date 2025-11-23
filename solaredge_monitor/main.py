# solaredge_monitor/main.py

from datetime import datetime
import logging
from pathlib import Path
import json

from .cli import build_parser
from .config import Config
from .logging import ConsoleLog, StructuredLog, RunLogEntry

from .services.modbus_reader import ModbusReader
from .services.notification_manager import NotificationManager
from .services.health_evaluator import HealthEvaluator
from .services.daylight_policy import DaylightPolicy
from .services.se_api_client import SolarEdgeAPIClient
from .services.daily_summary import DailySummaryService
from .services.output_formatter import emit_json, emit_human
from .services.alert_state import AlertStateManager
from .services.app_state import AppState
from .services.alert_logic import Alert
from .services.simulation_reader import SimulationReader
from .services.simulation_api_client import SimulationAPIClient
from .services import state_maintenance
from .services.weather_client import WeatherClient


def _log_weather_jsonl(path: str, run_ts, weather_estimate, snapshot_map, log) -> None:
    """Temporary JSONL logger for model tuning; safe to remove when no longer needed."""
    if not path or weather_estimate is None:
        return
    try:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        pac_map = {}
        if snapshot_map:
            for name, snap in snapshot_map.items():
                if snap and snap.pac_w is not None:
                    pac_map[name] = snap.pac_w
        # Skip logging when we have no inverter power data (nighttime/offline) or sun is below the horizon.
        if not pac_map:
            return
        if weather_estimate.snapshot.sun_elevation_deg is not None and weather_estimate.snapshot.sun_elevation_deg <= 0:
            return

        snap = weather_estimate.snapshot
        with target.open("a", encoding="utf-8") as fh:
            for name, inv in weather_estimate.per_inverter.items():
                row = {
                    "run_ts": run_ts.isoformat(),
                    "inverter": name,
                    "pac_w": pac_map.get(name),
                    "expected_ac_kw": inv.expected_ac_kw,
                    "expected_dc_kw": inv.expected_dc_kw,
                    "poa_wm2": inv.poa_wm2,
                    "cos_incidence": inv.cos_incidence,
                    "ghi_wm2": snap.ghi_wm2,
                    "dni_wm2": snap.dni_wm2,
                    "diffuse_wm2": snap.diffuse_wm2,
                    "cloud_cover_pct": snap.cloud_cover_pct,
                    "temp_c": snap.temp_c,
                    "sun_azimuth_deg": snap.sun_azimuth_deg,
                    "sun_elevation_deg": snap.sun_elevation_deg,
                    "array_kw_dc": inv.array_kw_dc,
                    "ac_capacity_kw": inv.ac_capacity_kw,
                    "dc_ac_derate": inv.dc_ac_derate,
                    "noct_c": inv.noct_c,
                    "temp_coeff_per_c": inv.temp_coeff_per_c,
                    "tilt_deg": inv.tilt_deg,
                    "azimuth_deg": inv.azimuth_deg,
                    "albedo": inv.albedo,
                    "provider": snap.provider,
                    "source_latitude": snap.source_latitude,
                    "source_longitude": snap.source_longitude,
                }
                fh.write(json.dumps(row) + "\n")
    except Exception as exc:  # pragma: no cover - non-critical logging
        log.debug("Weather tuning log skipped: %s", exc)


def _parse_simulated_time(raw: str | None, tz, log):
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        log.warning("Invalid simulated_time '%s'; using current time instead.", raw)
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def run_notify_test(notifier: NotificationManager, log, mode: str) -> None:
    if mode in ("healthy", "both"):
        log.info("[notify-test] Simulating healthy system (no alerts).")
        notifier.handle_alerts([])

    if mode in ("fault", "both"):
        log.info("[notify-test] Simulating fault with synthetic alert.")
        test_alert = Alert(
            inverter_name="TEST-INVERTER",
            serial="SIM-0000",
            message="CLI-triggered test fault",
            status=7,
            pac_w=0.0,
        )
        notifier.handle_alerts([test_alert])


def collect_modbus_snapshots(reader, state, now, log):
    snapshots_raw = reader.read_all()
    if isinstance(snapshots_raw, dict):
        snapshot_items = list(snapshots_raw.items())
        snapshot_map = snapshots_raw
    else:
        snapshot_items = [(s.name, s) for s in snapshots_raw]
        snapshot_map = {name: snap for name, snap in snapshot_items}

    serial_by_name: dict[str, str] = {}
    for name, snap in snapshot_map.items():
        if snap is None:
            continue
        serial = (snap.serial or name).upper()
        serial_by_name[name] = serial
        state.update_inverter_serial(name, serial)
        if snap.total_wh is not None:
            state.update_latest_total(serial, now.date(), snap.total_wh)

    return snapshot_map, snapshot_items, serial_by_name


def run_daily_summary(
    now,
    daylight_info,
    reader,
    summary_service,
    notifier,
    snapshot_map,
    cloud_inverters,
    se_client,
    app_cfg,
    log,
):
    if snapshot_map:
        summary_modbus = snapshot_map
    else:
        summary_modbus = reader.read_all()

    summary_inventory = cloud_inverters or None
    if app_cfg.solaredge_api.skip_at_night and daylight_info.skip_cloud:
        if se_client.enabled:
            log.info(
                "SolarEdge API skip-at-night active, but fetching cloud data for daily summary."
            )
            summary_inventory = se_client.fetch_inverters()
        else:
            summary_inventory = None

    summary = summary_service.run(
        now.date(),
        inventory=summary_inventory,
        modbus_snapshots=summary_modbus,
    )
    if summary:
        summary_text = summary_service.format_summary(summary)
        print("\n=== DAILY SUMMARY ===")
        print(summary_text)
        notifier.send_daily_summary(
            summary_text,
            summary.site_wh_modbus,
            summary.site_wh_api,
        )


def main():
    parser = build_parser()
    args = parser.parse_args()

    app_cfg = Config.load(args.config)
    console_logger = ConsoleLog(
        level="DEBUG" if args.debug else app_cfg.logging.console_level,
        quiet=args.quiet or app_cfg.logging.console_quiet,
        debug_modules=app_cfg.logging.debug_modules,
    )
    log = console_logger.setup()
    structured_logger = StructuredLog(
        app_cfg.logging.structured_path,
        app_cfg.logging.structured_enabled,
    )
    if args.debug:
        logging.getLogger("pymodbus").setLevel(logging.INFO)

    state_path = Path(app_cfg.state.path).expanduser() if app_cfg.state.path else None

    if args.command == "maintain-db":
        state = AppState(path=state_path)
        snap_days = args.snapshot_days if getattr(args, "snapshot_days", None) is not None else app_cfg.retention.snapshot_days
        summary_days = args.summary_days if getattr(args, "summary_days", None) is not None else app_cfg.retention.summary_days
        vacuum = not getattr(args, "no_vacuum", False)
        if vacuum is True and app_cfg.retention.vacuum_after_prune is False:
            vacuum = False
        state_maintenance.prune(state, snap_days, summary_days, vacuum=vacuum)
        log.info(
            "Database maintenance complete (snapshots>%sdays, summaries>%sdays removed)",
            snap_days,
            summary_days,
        )
        return

    # Determine simulation mode
    sim_cfg = app_cfg.simulation
    sim_cli_requested = args.command == "simulate"
    cli_scenario = getattr(args, "scenario", None)
    sim_scenario = cli_scenario or sim_cfg.scenario
    use_simulation = sim_cli_requested
    sim_root = sim_cfg.as_mapping() if use_simulation else None

    # Instantiate services
    state = AppState(path=state_path, persist=not use_simulation)
    notifier = NotificationManager(app_cfg.pushover, app_cfg.healthchecks, log)
    evaluator = HealthEvaluator(app_cfg.health, log)
    daylight_policy = DaylightPolicy(
        app_cfg.daylight,
        log,
        skip_modbus_at_night=app_cfg.modbus.skip_modbus_at_night,
        skip_cloud_at_night=app_cfg.solaredge_api.skip_at_night,
    )
    sim_time_override = None
    if use_simulation:
        sim_time_override = _parse_simulated_time(
            sim_cfg.simulated_time,
            daylight_policy.timezone,
            log,
        )

    if use_simulation:
        se_client = SimulationAPIClient(
            sim_scenario,
            sim_root,
            log,
            enabled=app_cfg.solaredge_api.enabled,
        )
    else:
        se_client = SolarEdgeAPIClient(app_cfg.solaredge_api, log)

    summary_service = DailySummaryService(app_cfg.modbus.inverters, se_client, log, state=state)
    alert_manager = AlertStateManager(log)
    weather_client = WeatherClient(app_cfg.weather, log)

    if args.command in {"health", "simulate"}:
        if use_simulation:
            reader = SimulationReader(sim_scenario, sim_root or {}, log)
        else:
            reader = ModbusReader(app_cfg.modbus, log)
        now = sim_time_override or datetime.now(daylight_policy.timezone)
        daylight_info = daylight_policy.get_info(now)

        cloud_inverters = []
        cloud_by_serial = {}
        optimizer_counts_by_serial: dict[str, int] = {}

        serial_by_name: dict[str, str] = {}
        weather_estimate = None

        if daylight_info.skip_modbus:
            log.info(
                "Nighttime phase detected (%s); skipping Modbus polling until sunrise %s",
                daylight_info.phase,
                daylight_info.sunrise.astimezone().strftime("%H:%M"),
            )
            snapshot_map = {}
            snapshot_items = []
            serial_by_name = {}
        else:
            snapshot_map, snapshot_items, serial_by_name = collect_modbus_snapshots(
                reader, state, now, log
            )

        if not use_simulation and weather_client.enabled:
            weather_estimate = weather_client.fetch(
                now,
                app_cfg.modbus.inverters,
                fallback_lat=app_cfg.daylight.latitude,
                fallback_lon=app_cfg.daylight.longitude,
            )

        if se_client.enabled and not daylight_info.skip_cloud:
            cloud_inverters = se_client.fetch_inverters()
            for inv in cloud_inverters:
                raw_serial = inv.serial or ""
                serial = raw_serial.upper()
                if not serial:
                    continue
                cloud_by_serial[serial] = inv
                cloud_by_serial[raw_serial] = inv
                serial_by_name.setdefault(inv.name, serial)
        else:
            for cfg in app_cfg.modbus.inverters:
                serial = state.get_inverter_serial(cfg.name)
                if serial:
                    serial_by_name.setdefault(cfg.name, serial)

        # --- stdout output ---
        if not args.quiet:
            if args.json:
                emit_json(snapshot_items, cloud_by_serial, weather_estimate=weather_estimate)
            else:
                emit_human(snapshot_items, cloud_by_serial, weather_estimate=weather_estimate)

        health = None
        if snapshot_items:
            health = evaluator.evaluate(snapshot_map, low_light_grace=daylight_info.in_grace_window)

        optimizer_mismatches: list[tuple[str, int, int | None]] = []
        has_optimizer_expectations = any(
            inv_cfg.expected_optimizers is not None for inv_cfg in app_cfg.modbus.inverters
        )

        if se_client.enabled and not daylight_info.skip_cloud:
            optimizer_counts_by_serial = se_client.get_optimizer_counts(cloud_inverters or None)
        if se_client.enabled and not daylight_info.skip_cloud and has_optimizer_expectations:
            log.debug(
                "Optimizer counts fetched: %s",
                {k: optimizer_counts_by_serial[k] for k in sorted(optimizer_counts_by_serial)},
            )
            optimizer_mismatches = evaluator.update_with_optimizer_counts(
                health,
                app_cfg.modbus.inverters,
                serial_by_name,
                optimizer_counts_by_serial,
            )
        elif se_client.enabled and daylight_info.skip_cloud and has_optimizer_expectations:
            log.info("SolarEdge API polling skipped at night (configuration).")

        alerts = alert_manager.build_alerts(
            now=now,
            health=health,
            optimizer_mismatches=optimizer_mismatches,
        )

        if log.isEnabledFor(logging.DEBUG):
            for alert in alerts:
                log.debug(
                    "Alert [%s] serial=%s status=%s pac=%s reason=%s",
                    alert.inverter_name,
                    alert.serial,
                    alert.status,
                    alert.pac_w,
                    alert.message,
                )

        if daylight_info.skip_modbus:
            log.info(
                "Modbus polling skipped; suppressing Healthchecks ping until monitoring resumes."
            )
        else:
            notifier.handle_alerts(alerts, health=health)

        if (
            args.command == "health"
            and not use_simulation
            and snapshot_map
        ):
            try:
                state.log_health_run(
                    run_timestamp=now,
                    daylight_phase=daylight_info.phase,
                    snapshots=snapshot_map,
                    health=health,
                    cloud_by_serial=cloud_by_serial,
                    optimizer_counts=optimizer_counts_by_serial,
                )
            except Exception as exc:
                log.warning("Failed to record health run: %s", exc)

        if weather_estimate and app_cfg.weather.log_path and not use_simulation:
            _log_weather_jsonl(
                app_cfg.weather.log_path,
                now,
                weather_estimate,
                snapshot_map,
                log,
            )

        daylight_ctx = None
        if daylight_info:
            daylight_ctx = {
                "phase": daylight_info.phase,
                "is_daylight": daylight_info.is_daylight,
                "in_grace_window": daylight_info.in_grace_window,
                "production_day_over": daylight_info.production_day_over,
                "skip_modbus": daylight_info.skip_modbus,
                "skip_cloud": daylight_info.skip_cloud,
                "sunrise": getattr(daylight_info, "sunrise", None),
                "sunrise_grace_end": getattr(daylight_info, "sunrise_grace_end", None),
                "sunset": getattr(daylight_info, "sunset", None),
                "sunset_grace_start": getattr(daylight_info, "sunset_grace_start", None),
                "production_over_at": getattr(daylight_info, "production_over_at", None),
            }

        residuals = None
        if snapshot_map and weather_estimate and weather_estimate.per_inverter:
            res_map: dict[str, dict[str, float | None]] = {}
            for name, snap in snapshot_map.items():
                inv = weather_estimate.per_inverter.get(name)
                if not inv or snap is None:
                    continue
                if snap.pac_w is None or inv.expected_ac_kw is None:
                    continue
                expected_w = inv.expected_ac_kw * 1000
                if expected_w <= 0:
                    continue
                res_map[name] = {
                    "pac_w": snap.pac_w,
                    "expected_ac_w": expected_w,
                    "residual_w": snap.pac_w - expected_w,
                    "ratio": snap.pac_w / expected_w if expected_w else None,
                }
            residuals = res_map or None

        if structured_logger.enabled:
            run_entry = RunLogEntry(
                timestamp=now.isoformat(),
                daylight_phase=getattr(daylight_info, "phase", None),
                daylight_context=daylight_ctx,
                inverter_snapshots=snapshot_map or None,
                weather_snapshot=weather_estimate.snapshot if weather_estimate else None,
                weather_expectations=weather_estimate.per_inverter if weather_estimate else None,
                residuals=residuals,
                health=health,
                alerts=alerts,
                cloud_inventory=cloud_inverters or None,
                optimizer_counts=optimizer_counts_by_serial or None,
            )
            structured_logger.write(run_entry)

        should_run_summary = summary_service.should_run(now.date(), daylight_info)
        if should_run_summary:
            run_daily_summary(
                now=now,
                daylight_info=daylight_info,
                reader=reader,
                summary_service=summary_service,
                notifier=notifier,
                snapshot_map=snapshot_map,
                cloud_inverters=cloud_inverters,
                se_client=se_client,
                app_cfg=app_cfg,
                log=log,
            )
    elif args.command == "notify-test":
        run_notify_test(notifier, log, args.mode)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    state.flush()


if __name__ == "__main__":
    main()
