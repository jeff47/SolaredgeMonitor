# solaredge_monitor/main.py

from datetime import datetime

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


def main():
    parser = build_parser()
    args = parser.parse_args()

    app_cfg = Config.load(args.config)
    log = setup_logging(debug=args.debug, quiet=args.quiet)

    # Instantiate services
    notifier = NotificationManager(app_cfg.pushover, app_cfg.healthchecks, log)
    evaluator = HealthEvaluator(app_cfg.health, log)
    daylight_policy = DaylightPolicy(app_cfg.daylight, log)
    se_client = SolarEdgeAPIClient(app_cfg.solaredge_api, log)
    summary_service = DailySummaryService(app_cfg.modbus.inverters, se_client, log)
    alert_manager = AlertStateManager(log)

    if args.command == "health":
        reader = ModbusReader(app_cfg.modbus, log)
        now = datetime.now()
        daylight_info = daylight_policy.get_info(now)
        se_skip = daylight_info.skip_modbus and app_cfg.solaredge_api.skip_at_night

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
                if snap is not None and snap.serial:
                    serial_by_name[name] = snap.serial.upper()

        if se_client.enabled and not se_skip:
            cloud_inverters = se_client.fetch_inverters()
            cloud_by_serial = {inv.serial: inv for inv in cloud_inverters}
            for inv in cloud_inverters:
                serial = (inv.serial or "").upper()
                if not serial:
                    continue
                serial_by_name.setdefault(inv.name, serial)

        # --- stdout output ---
        if snapshot_items and not args.quiet:
            if args.json:
                emit_json(snapshot_items, cloud_by_serial)
            else:
                emit_human(snapshot_items, cloud_by_serial)

        health = None
        if snapshot_items:
            health = evaluator.evaluate(snapshot_map, low_light_grace=daylight_info.in_grace_window)

        expected_counts = {
            cfg_inv.name: cfg_inv.expected_optimizers
            for cfg_inv in app_cfg.modbus.inverters
            if cfg_inv.expected_optimizers is not None
        }
        optimizer_mismatches: list[tuple[str, int, int | None]] = []

        if se_client.enabled and not se_skip and expected_counts:
            optimizer_counts_by_serial = se_client.get_optimizer_counts(cloud_inverters or None)
            optimizer_mismatches = evaluator.optimizer_mismatches_from_counts(
                expected_counts,
                serial_by_name,
                optimizer_counts_by_serial,
            )
        elif se_client.enabled and se_skip:
            log.info("SolarEdge API polling skipped at night (configuration).")

        if health and optimizer_mismatches:
            evaluator.apply_optimizer_mismatches(health, optimizer_mismatches)

        alerts = alert_manager.build_alerts(
            now=now,
            health=health,
            optimizer_mismatches=optimizer_mismatches,
        )

        notifier.handle_alerts(alerts)

        should_run_summary = summary_service.should_run(now.date(), daylight_info)
        if should_run_summary:
            if se_skip and app_cfg.solaredge_api.skip_at_night:
                log.info(
                    "Running daily summary despite nightly SolarEdge API skip setting."
                )
            summary_inventory = (
                None if (se_skip and app_cfg.solaredge_api.skip_at_night)
                else (cloud_inverters or None)
            )
            summary_service.run(now.date(), inventory=summary_inventory)
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


if __name__ == "__main__":
    main()
