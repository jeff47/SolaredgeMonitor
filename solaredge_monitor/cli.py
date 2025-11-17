# solaredge_monitor/cli.py
import argparse

def build_parser():
    parser = argparse.ArgumentParser(
        prog="solaredge-monitor",
        description="SolarEdge System Health Monitor"
    )

    parser.add_argument(
        "--config",
        default="solaredge_monitor.conf",
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
        help="Suppress stdout output (cron-friendly)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # For Stage 1 we only support the 'health' command.
    sub.add_parser("health", help="Run a one-shot health check")

    return parser
