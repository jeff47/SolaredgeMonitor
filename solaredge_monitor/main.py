# solaredge_monitor/main.py
from .cli import build_parser
from .config import Config
from .util.logging import setup_logging

from .services.modbus_reader import ModbusReader
from .services.se_api_client import SolarEdgeAPIClient
from .services.daylight_policy import DaylightPolicy
from .services.health_evaluator import HealthEvaluator
from .services.alert_state import AlertStateManager
from .services.notification_manager import NotificationManager
from .services.daily_summary import DailySummaryService
from .services.simulation_reader import SimulationReader


def main():
    parser = build_parser()
    args = parser.parse_args()

    cfg = Config.load(args.config)
    log = setup_logging(debug=args.debug, quiet=args.quiet)

    # Reader selection (simulation overrides)
    if args.command == "simulate":
        reader = SimulationReader(args.fault, cfg.simulation, log)
    else:
        reader = ModbusReader(cfg.modbus, log)

    api = SolarEdgeAPIClient(cfg.api, log)
    daylight = DaylightPolicy(cfg.daylight, log)
    health_eval = HealthEvaluator(cfg.health, log)
    alerts = AlertStateManager(cfg.alerts, log)
    notify = NotificationManager(cfg.notify, log)
    summary = DailySummaryService(cfg.summary, api, log)

    if args.command == "health":
        # TBD
        #run_health_check(cfg, reader, api, daylight, health_eval, alerts, notify, log)
        pass


    elif args.command == "daily-summary":
        # TBD
        #run_daily_summary(cfg, api, summary, notify, log)
        pass

    elif args.command == "simulate":
        # TBD
        #run_health_check(cfg, reader, api, daylight, health_eval, alerts, notify, log)
        pass
