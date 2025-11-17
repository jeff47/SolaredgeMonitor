#!/usr/bin/env python3
"""Quick helper to inspect SolarEdge cloud data."""

from datetime import date

from solaredge_monitor.config import Config
from solaredge_monitor.services.se_api_client import SolarEdgeAPIClient
from solaredge_monitor.util.logging import setup_logging


def main() -> None:
    log = setup_logging(debug=True)
    cfg = Config.load("solaredge_monitor.conf")
    client = SolarEdgeAPIClient(cfg.solaredge_api, log)

    print("Enabled?", client.enabled)

    inventory = client.fetch_inverters() if client.enabled else []
    print("Inverters:")
    for inv in inventory:
        print(
            f" - {inv.serial} {inv.name} status={inv.status} "
            f"optimizers={inv.connected_optimizers}"
        )

    counts = client.get_optimizer_counts(inventory)
    print("Optimizer counts:", counts)

    energy = client.get_daily_production(date.today())
    print("Today's energy:", energy)

    print("Optimizer alerts:", client.check_optimizer_expectations(inventory))


if __name__ == "__main__":
    main()
