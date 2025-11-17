# solaredge_monitor/main.py

from datetime import datetime
import json

from .cli import build_parser
from .config import Config
from .util.logging import setup_logging

from .services.modbus_reader import ModbusReader
from .services.alert_logic import evaluate_alerts
from .services.notification_manager import NotificationManager


def main():
    parser = build_parser()
    args = parser.parse_args()

    app_cfg = Config.load(args.config)
    log = setup_logging(debug=args.debug, quiet=args.quiet)

    # Instantiate services
    reader = ModbusReader(app_cfg.modbus, log)
    notifier = NotificationManager(app_cfg.pushover, app_cfg.healthchecks, log)

    if args.command == "health":
        now = datetime.now()
        snapshots = reader.read_all()

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
                    for s in snapshots
                ]
                print(json.dumps({"inverters": payload}, indent=2))
            else:
                # Human-readable output
                for s in snapshots:
                    if s.error:
                        print(f"[{s.name}] ERROR: {s.error}")
                    else:
                        print(
                            f"[{s.name}] PAC={s.pac_w or 0:.0f}W  "
                            f"Vdc={s.vdc_v or 0:.1f}V  status={s.status}"
                        )

        # --- Alerts + notifications ---
        alerts = evaluate_alerts(snapshots, now)
        notifier.handle_alerts(alerts)
