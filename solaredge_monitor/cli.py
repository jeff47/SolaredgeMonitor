# solaredge_monitor/cli.py
import argparse

def build_parser():
    parser = argparse.ArgumentParser(
        prog="solaredge-monitor",
        description="SolarEdge System Health Monitor"
    )

    parser.add_argument(
        "--config",
        default="/etc/solaredge-monitor.conf",
        help="Path to configuration file"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging"
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output (cron-friendly)"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="Run system health check")
    sub.add_parser("daily-summary", help="Send daily production summary")

    sim = sub.add_parser("simulate", help="Simulate fault conditions")
    sim.add_argument(
        "--fault",
        required=True,
        choices=["offline", "low-output", "safedc", "no-optimizers"],
        help="Fault type to simulate"
    )

    return parser
