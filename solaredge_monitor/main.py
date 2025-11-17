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
from .services.daylight_policy import DaylightPolicy
from .services.se_api_client import SolarEdgeAPIClient


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

    if args.command == "health":
        reader = ModbusReader(app_cfg.modbus, log)
        now = datetime.now()
        daylight_info = daylight_policy.get_info(now)
        se_skip = daylight_info.skip_modbus and app_cfg.solaredge_api.skip_at_night

        alerts: list[Alert] = []

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

        # --- stdout output ---
        if snapshot_items and not args.quiet:
            if args.json:
                # JSON output
                payload = []
                for name, s in snapshot_items:
                    if s is None:
                        payload.append({"name": name, "error": "No Modbus data"})
                        continue
                    cloud_status = None
                    if cloud_by_serial and s.serial:
                        inv = cloud_by_serial.get(s.serial.upper())
                        if inv:
                            cloud_status = inv.status
                    payload.append(
                        {
                            "name": s.name,
                            "serial": s.serial,
                            "model": s.model,
                            "status": s.status,
                            "cloud_status": cloud_status,
                            "pac_w": s.pac_w,
                            "vdc_v": s.vdc_v,
                            "idc_a": s.idc_a,
                            "error": s.error,
                        }
                    )
                print(json.dumps({"inverters": payload}, indent=2))
            else:
                # Human-readable output
                for name, s in snapshot_items:
                    if s is None:
                        print(f"[{name}] OFFLINE: no Modbus data")
                    elif s.error:
                        print(f"[{name}] ERROR: {s.error}")
                    else:
                        cloud_status = None
                        if cloud_by_serial and s.serial:
                            inv = cloud_by_serial.get(s.serial.upper())
                            if inv:
                                cloud_status = inv.status
                        cloud_txt = f" cloud={cloud_status}" if cloud_status is not None else ""
                        print(
                            f"[{name}] PAC={s.pac_w or 0:.0f}W  "
                            f"Vdc={s.vdc_v or 0:.1f}V  status={s.status}{cloud_txt}"
                        )

        health = None
        if snapshot_items:
            health = evaluator.evaluate(snapshot_map, low_light_grace=daylight_info.in_grace_window)

        expected_counts = {
            cfg_inv.name: cfg_inv.expected_optimizers
            for cfg_inv in app_cfg.modbus.inverters
            if cfg_inv.expected_optimizers is not None
        }
        mismatched_optimizer_inverters: dict[str, tuple[int, int | None]] = {}

        if se_client.enabled and not se_skip and expected_counts:
            api_messages = se_client.check_optimizer_expectations(cloud_inverters or None)
            optimizer_counts = se_client.get_optimizer_counts(cloud_inverters or None)

            for inv_cfg in app_cfg.modbus.inverters:
                expected = inv_cfg.expected_optimizers
                if expected is None:
                    continue

                # Determine serial by matching against cloud inventory
                serial = serial_by_name.get(inv_cfg.name)
                if not serial:
                    for cloud in cloud_inverters:
                        if cloud.name == inv_cfg.name:
                            serial = (cloud.serial or "").upper()
                            break
                if not serial:
                    continue

                actual = optimizer_counts.get(serial)
                if actual != expected:
                    mismatched_optimizer_inverters[inv_cfg.name] = (expected, actual)

            for msg in api_messages:
                alerts.append(
                    Alert(
                        inverter_name="CLOUD",
                        serial="CLOUD",
                        message=msg,
                        status=-1,
                        pac_w=None,
                    )
                )
        elif se_client.enabled and se_skip:
            log.info("SolarEdge API polling skipped at night (configuration).")

        if health:
            for inv_name, (expected, actual) in mismatched_optimizer_inverters.items():
                inv_state = health.per_inverter.get(inv_name)
                if not inv_state:
                    continue
                actual_txt = "unknown" if actual is None else str(actual)
                reason = (
                    f"Optimizer count mismatch (expected {expected}, cloud={actual_txt})"
                )
                if inv_state.reason:
                    inv_state.reason += "; " + reason
                else:
                    inv_state.reason = reason
                inv_state.inverter_ok = False

            alerts.extend(evaluate_alerts(health, now))
        elif mismatched_optimizer_inverters:
            for inv_name, (expected, actual) in mismatched_optimizer_inverters.items():
                actual_txt = "unknown" if actual is None else str(actual)
                alerts.append(
                    Alert(
                        inverter_name=inv_name,
                        serial="CLOUD",
                        message=f"Optimizer count mismatch (expected {expected}, cloud={actual_txt})",
                        status=-1,
                        pac_w=None,
                    )
                )

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
