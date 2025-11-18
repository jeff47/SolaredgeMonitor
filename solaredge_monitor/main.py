# solaredge_monitor/main.py

from datetime import datetime
from pathlib import Path

from .cli import build_parser
from .config import Config
from .util.logging import setup_logging

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


def main():
    parser = build_parser()
    args = parser.parse_args()

    app_cfg = Config.load(args.config)
    log = setup_logging(debug=args.debug, quiet=args.quiet)

    # Instantiate services
    state_path = Path(app_cfg.state.path).expanduser() if app_cfg.state.path else None
    state = AppState(path=state_path)
    notifier = NotificationManager(app_cfg.pushover, app_cfg.healthchecks, log)
    evaluator = HealthEvaluator(app_cfg.health, log)
    daylight_policy = DaylightPolicy(app_cfg.daylight, log)
    se_client = SolarEdgeAPIClient(app_cfg.solaredge_api, log)
    summary_service = DailySummaryService(app_cfg.modbus.inverters, se_client, log, state=state)
    alert_manager = AlertStateManager(log)

    if args.command == "health":
        reader = ModbusReader(app_cfg.modbus, log)
        now = datetime.now(daylight_policy.timezone)
        daylight_info = daylight_policy.get_info(now)
        is_night = daylight_info.phase == "NIGHT"
        se_skip = bool(app_cfg.solaredge_api.skip_at_night and is_night)

        cloud_inverters = []
        cloud_by_serial = {}

        serial_by_name: dict[str, str] = {}

        if daylight_info.skip_modbus:
            log.info(
                "Nighttime phase detected (%s); skipping Modbus polling until sunrise %s",
                daylight_info.phase,
                daylight_info.sunrise.astimezone().strftime("%H:%M"),
            )
            snapshot_items = []
            snapshot_map = {}
        else:
            snapshots_raw = reader.read_all()
            if isinstance(snapshots_raw, dict):
                snapshot_items = list(snapshots_raw.items())
                snapshot_map = snapshots_raw
            else:
                snapshot_items = [(s.name, s) for s in snapshots_raw]
                snapshot_map = {name: snap for name, snap in snapshot_items}

            for name, snap in snapshot_map.items():
                if snap is None:
                    continue
                serial = (snap.serial or name).upper()
                serial_by_name[name] = serial
                state.update_inverter_serial(name, serial)
                if snap.total_wh is not None:
                    state.update_latest_total(serial, now.date(), snap.total_wh)

        if se_client.enabled and not se_skip:
            cloud_inverters = se_client.fetch_inverters()
            cloud_by_serial = {inv.serial: inv for inv in cloud_inverters}
            for inv in cloud_inverters:
                serial = (inv.serial or "").upper()
                if not serial:
                    continue
                serial_by_name.setdefault(inv.name, serial)
        else:
            for cfg in app_cfg.modbus.inverters:
                serial = state.get_inverter_serial(cfg.name)
                if serial:
                    serial_by_name.setdefault(cfg.name, serial)

        # --- stdout output ---
        if snapshot_items and not args.quiet:
            if args.json:
                emit_json(snapshot_items, cloud_by_serial)
            else:
                emit_human(snapshot_items, cloud_by_serial)

        health = None
        if snapshot_items:
            health = evaluator.evaluate(snapshot_map, low_light_grace=daylight_info.in_grace_window)

        optimizer_mismatches: list[tuple[str, int, int | None]] = []
        has_optimizer_expectations = any(
            inv_cfg.expected_optimizers is not None for inv_cfg in app_cfg.modbus.inverters
        )

        if se_client.enabled and not se_skip and has_optimizer_expectations:
            optimizer_counts_by_serial = se_client.get_optimizer_counts(cloud_inverters or None)
            optimizer_mismatches = evaluator.update_with_optimizer_counts(
                health,
                app_cfg.modbus.inverters,
                serial_by_name,
                optimizer_counts_by_serial,
            )
        elif se_client.enabled and se_skip and has_optimizer_expectations:
            log.info("SolarEdge API polling skipped at night (configuration).")

        alerts = alert_manager.build_alerts(
            now=now,
            health=health,
            optimizer_mismatches=optimizer_mismatches,
        )

        if daylight_info.skip_modbus:
            log.info(
                "Modbus polling skipped; suppressing Healthchecks ping until monitoring resumes."
            )
        else:
            notifier.handle_alerts(alerts)

        should_run_summary = summary_service.should_run(now.date(), daylight_info)
        if should_run_summary:
            if snapshot_map:
                summary_modbus = snapshot_map
            else:
                summary_modbus = reader.read_all()
            summary_inventory = cloud_inverters or None
            if se_skip and app_cfg.solaredge_api.skip_at_night:
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
    elif args.command == "notify-test":
        mode = args.mode

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
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    state.flush()


if __name__ == "__main__":
    main()
