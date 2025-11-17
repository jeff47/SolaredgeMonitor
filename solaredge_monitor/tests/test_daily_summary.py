from datetime import date
from pathlib import Path
from types import SimpleNamespace

from solaredge_monitor.config import InverterConfig
from solaredge_monitor.services.daily_summary import DailySummaryService
from solaredge_monitor.services.se_api_client import CloudInverter
from solaredge_monitor.util.logging import get_logger, setup_logging


setup_logging(debug=False)
LOG = get_logger("daily-summary-test")


class FakeApi:
    def __init__(self, site_wh=5000.0, per_inv=None, inventory=None):
        self.enabled = True
        self.site_wh = site_wh
        self.per_inv = per_inv or {}
        self.inventory = inventory or []

    def fetch_inverters(self):
        return self.inventory

    def get_daily_production(self, day):
        return self.site_wh

    def get_inverter_daily_energy(self, serial, day):
        if serial is None:
            return None
        return self.per_inv.get(serial.upper())


def test_daily_summary_runs_once(tmp_path):
    inventory = [
        CloudInverter(
            serial="INV-A-123",
            name="INV-A",
            status=None,
            model=None,
            connected_optimizers=None,
            raw={},
        ),
        CloudInverter(
            serial="INV-B-456",
            name="INV-B",
            status=None,
            model=None,
            connected_optimizers=None,
            raw={},
        ),
    ]
    per_inv = {"INV-A-123": 2000.0, "INV-B-456": 1500.0}
    api = FakeApi(site_wh=4000.0, per_inv=per_inv, inventory=inventory)

    svc = DailySummaryService(
        inverter_cfgs=[
            InverterConfig(name="INV-A", host="h", port=1, unit=1),
            InverterConfig(name="INV-B", host="h", port=2, unit=1),
        ],
        api_client=api,
        log=LOG,
        state_path=tmp_path / "state.json",
    )

    info = SimpleNamespace(production_day_over=True)
    today = date(2024, 6, 1)

    assert svc.should_run(today, info)
    summary = svc.run(today)
    assert summary is not None
    assert summary.site_wh == 4000.0
    energies = dict(summary.per_inverter_wh)
    assert energies["INV-A"] == 2000.0
    assert not svc.should_run(today, info)
