# solaredge_monitor/main.py

from datetime import datetime
import json

from .cli import build_parser
from .config import Config
from .util.logging import setup_logging

from .services.modbus_reader import ModbusReader
from .services.alert_logic import evaluate_alerts, Alert
from .services.notification_manager import NotificationManager
from .services.health_evaluator import HealthEvaluator


def main():
    parser = build_parser()
    args = parser.parse_args()

    app_cfg = Config.load(args.config)
    log = setup_logging(debug=args.debug, quiet=args.quiet)

    # Instantiate services
    notifier = NotificationManager(app_cfg.pushover, app_cfg.healthchecks, log)
    evaluator = HealthEvaluator(app_cfg.health, log)

    if args.command == "health":
        reader = ModbusReader(app_cfg.modbus, log)
        now = datetime.now()
        snapshots_raw = reader.read_all()

        if isinstance(snapshots_raw, dict):
            snapshot_list = [s for s in snapshots_raw.values() if s is not None]
            snapshot_map = snapshots_raw
        else:
            snapshot_list = [s for s in snapshots_raw if s is not None]
            snapshot_map = {s.name: s for s in snapshot_list}

        # --- stdout output ---
        if not args.quiet:
            if args.json:
                # JSON output
                payload = [
                    {
                        "name": s.name,
                        "serial": s.serial,
                        "model": s.model,
                        "status": s.status,
                        "pac_w": s.pac_w,
                        "vdc_v": s.vdc_v,
                        "idc_a": s.idc_a,
                        "error": s.error,
                    }
                    for s in snapshot_list
                ]
                print(json.dumps({"inverters": payload}, indent=2))
            else:
                # Human-readable output
                for s in snapshot_list:
                    if s.error:
                        print(f"[{s.name}] ERROR: {s.error}")
                    else:
                        print(
                            f"[{s.name}] PAC={s.pac_w or 0:.0f}W  "
                            f"Vdc={s.vdc_v or 0:.1f}V  status={s.status}"
                        )

        health = evaluator.evaluate(snapshot_map)

        # --- Alerts + notifications ---
        alerts = evaluate_alerts(health, now)
        notifier.handle_alerts(alerts)
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
