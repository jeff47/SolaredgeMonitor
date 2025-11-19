from datetime import date
import logging

from solaredge_monitor.services.simulation_reader import SimulationReader
from solaredge_monitor.services.simulation_api_client import SimulationAPIClient


LOG = logging.getLogger("simulation-tests")


def _sample_simulation_config():
    return {
        "inverters": "INV-A, INV-B",
        "inverter_status": "INV-A:4, INV-B:2",
        "inverter_pac_w": "INV-A:3200, INV-B:150",
        "inverter_vdc": "INV-A:400, INV-B:50",
        "inverter_idc": "INV-A:8, INV-B:0.5",
        "inverter_total_wh": "INV-A:120000, INV-B:118000",
        "inverter_serial": "INV-A:INV-A-123, INV-B:INV-B-456",
        "inverter_optimizers": "INV-A:26, INV-B:19",
        "inverter_daily_wh": "INV-A-123:2500, INV-B-456:600",
        "sunset": {
            "inverter_status": "INV-A:5, INV-B:1",
            "inverter_pac_w": "INV-A:50, INV-B:0",
            "inverter_total_wh": "INV-A:120150, INV-B:118200",
            "inverter_daily_wh": "INV-A-123:300, INV-B-456:0",
            "inverter_optimizers": "INV-A:25, INV-B:18",
        },
    }


def test_simulation_reader_merges_root_and_scenario():
    cfg = _sample_simulation_config()
    reader = SimulationReader("sunset", cfg, LOG)

    snapshots = reader.read_all()
    by_name = {snap.name: snap for snap in snapshots}

    assert set(by_name.keys()) == {"INV-A", "INV-B"}
    inv_a = by_name["INV-A"]
    inv_b = by_name["INV-B"]

    # Scenario overrides should take precedence
    assert inv_a.pac_w == 50.0
    assert inv_b.pac_w == 0.0
    assert inv_b.status == 1
    # Root values fill in when scenario omits keys
    assert inv_a.vdc_v == 400.0
    assert inv_a.idc_a == 8.0
    assert inv_a.total_wh == 120150.0
    assert inv_b.total_wh == 118200.0


def test_simulation_api_client_provides_inventory_and_energy():
    cfg = _sample_simulation_config()
    client = SimulationAPIClient("sunset", cfg, LOG, enabled=True)

    inventory = client.fetch_inverters()
    assert len(inventory) == 2
    inv_a = next(inv for inv in inventory if inv.name == "INV-A")
    assert inv_a.serial == "INV-A-123"
    assert inv_a.connected_optimizers == 25  # scenario override

    counts = client.get_optimizer_counts(inventory)
    assert counts["INV-A-123"] == 25
    assert counts["INV-B-456"] == 18

    site_wh = client.get_daily_production(date(2024, 6, 1))
    # 300 + 0 per scenario
    assert site_wh == 300.0

    energy_a = client.get_inverter_daily_energy("inv-a-123", date(2024, 6, 1))
    assert energy_a == 300.0
    energy_b = client.get_inverter_daily_energy("INV-B-456", date(2024, 6, 1))
    assert energy_b == 0.0
