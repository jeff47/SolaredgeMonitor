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

    # One-shot health check
    sub.add_parser("health", help="Run a one-shot health check")

    # Simulation-driven health check
    cmd_sim = sub.add_parser(
        "simulate",
        help="Run a one-shot health check using simulated inputs",
    )
    cmd_sim.add_argument(
        "--scenario",
        help="Override [simulation] scenario name",
    )

    # Notification test helper
    cmd_notify = sub.add_parser(
        "notify-test",
        help="Send test notifications for healthy/fault scenarios",
    )
    cmd_notify.add_argument(
        "--mode",
        choices=("healthy", "fault", "both"),
        default="both",
        help="Which scenario(s) to simulate when sending notifications",
    )

    return parser
