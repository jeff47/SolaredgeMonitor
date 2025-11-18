# solaredge_monitor/tests/test_se_api_client.py

from datetime import date

from solaredge_monitor.config import SolarEdgeAPIConfig
from solaredge_monitor.services.se_api_client import CloudInverter, SolarEdgeAPIClient
from solaredge_monitor.util.logging import get_logger, setup_logging


setup_logging(debug=False)
LOG = get_logger("se-api-test")


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        status_code, payload = self.responses.get(url, (404, {}))
        if isinstance(status_code, Exception):
            raise status_code
        return FakeResponse(status_code=status_code, payload=payload)


def _cfg(**overrides):
    cfg = SolarEdgeAPIConfig(
        enabled=True,
        api_key="KEY",
        site_id="123",
        base_url="https://api.test",
        timeout=5,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_disabled_client_short_circuits():
    cfg = _cfg(enabled=False)
    client = SolarEdgeAPIClient(cfg, LOG)

    assert client.fetch_inverters() == []
    assert client.get_optimizer_counts() == {}
    assert client.get_daily_production(date.today()) is None


def test_inventory_parsing_variants():
    inventory_payload = {
        "Inventory": {
            "Inverters": [
                {
                    "serialNumber": "123-456",
                    "name": "Roof East",
                    "model": "SE10000H",
                    "status": {"status": "UP"},
                    "connectedOptimizers": 12,
                },
                {
                    "serial": "789",
                    "status": "Fault",
                    "optimizers": [1, 2, 3],
                },
            ]
        }
    }
    session = FakeSession({
        "https://api.test/site/123/inventory": (200, inventory_payload)
    })
    client = SolarEdgeAPIClient(_cfg(), LOG, session=session)

    invs = client.fetch_inverters()
    assert [i.serial for i in invs] == ["123-456", "789"]
    assert invs[0].connected_optimizers == 12
    assert invs[1].connected_optimizers == 3


def test_optimizer_counts_include_serial_base_variant():
    client = SolarEdgeAPIClient(_cfg(), LOG)
    cloud = [
        CloudInverter(
            serial="ABC123-XY",
            name="Roof Inverter",
            status=None,
            model=None,
            connected_optimizers=19,
            raw={},
        )
    ]

    counts = client.get_optimizer_counts(cloud)
    assert counts["ABC123-XY"] == 19
    assert counts["ABC123"] == 19


def test_get_daily_production_parses_value():
    energy_payload = {
        "energy": {
            "values": [
                {"date": "2024-06-01 00:00:00", "value": 42.5}
            ]
        }
    }
    session = FakeSession({
        "https://api.test/site/123/energy": (200, energy_payload)
    })
    client = SolarEdgeAPIClient(_cfg(), LOG, session=session)

    energy = client.get_daily_production(date(2024, 6, 1))
    assert energy == 42.5


def test_optimizer_expectation_alerts():
    inventory_payload = {
        "inventory": {
            "inverters": [
                {
                    "serialNumber": "AA111",
                    "name": "INV-A",
                    "connectedOptimizers": 8,
                }
            ]
        }
    }
    session = FakeSession({
        "https://api.test/site/123/inventory": (200, inventory_payload)
    })
    client = SolarEdgeAPIClient(_cfg(), LOG, session=session)

    alerts = client.check_optimizer_expectations({"INV-A": 10})
    assert alerts == ["[INV-A] Optimizer count mismatch (expected 10, got 8)"]


def test_get_inverter_daily_energy(tmp_path):
    equipment_payload = {
        "data": {
            "values": [
                {"date": "2024-06-01 10:00:00", "value": 10},
                {"date": "2024-06-01 14:00:00", "value": 5},
            ]
        }
    }
    session = FakeSession({
        "https://api.test/site/123/equipment/ABC/data": (200, equipment_payload)
    })
    client = SolarEdgeAPIClient(_cfg(), LOG, session=session)

    energy = client.get_inverter_daily_energy("abc", date(2024, 6, 1))
    assert energy == 15
