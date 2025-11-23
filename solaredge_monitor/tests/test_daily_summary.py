from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from solaredge_monitor.config import InverterConfig
from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.services.daily_summary import DailySummaryService
from solaredge_monitor.services.se_api_client import CloudInverter
from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.logging import ConsoleLog, get_logger


ConsoleLog(level="INFO", quiet=True).setup()
LOG = get_logger("daily-summary-test")


class FakeApi:
    def __init__(self, site_wh=5000.0, per_inv=None, inventory=None, enabled=True):
        self.enabled = enabled
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
    api = FakeApi(site_wh=None, per_inv={}, inventory=inventory, enabled=False)
    state_path = tmp_path / "state.json"
    state = AppState(path=state_path)
    state.update_inverter_serial("INV-A", "INV-A-123")
    state.update_inverter_serial("INV-B", "INV-B-456")
    prev_day = date(2024, 5, 31)
    state.set_summary_baseline("INV-A-123", prev_day, 1000.0)
    state.set_summary_baseline("INV-B-456", prev_day, 2000.0)

    svc = DailySummaryService(
        inverter_cfgs=[
            InverterConfig(name="INV-A", host="h", port=1, unit=1),
            InverterConfig(name="INV-B", host="h", port=2, unit=1),
        ],
        api_client=api,
        log=LOG,
        state=state,
    )

    info = SimpleNamespace(production_day_over=True)
    today = date(2024, 6, 1)

    assert svc.should_run(today, info)
    snapshots = {
        "INV-A": InverterSnapshot(
            name="INV-A",
            serial="INV-A-123",
            model="SIM",
            status=4,
            vendor_status=None,
            pac_w=0,
            vdc_v=0,
            idc_a=0,
            total_wh=3000.0,
            error=None,
            timestamp=datetime.now(),
        ),
        "INV-B": InverterSnapshot(
            name="INV-B",
            serial="INV-B-456",
            model="SIM",
            status=4,
            vendor_status=None,
            pac_w=0,
            vdc_v=0,
            idc_a=0,
            total_wh=3500.0,
            error=None,
            timestamp=datetime.now(),
        ),
    }

    summary = svc.run(today, inventory=inventory, modbus_snapshots=snapshots)
    assert summary is not None
    assert summary.site_wh_modbus == 3500.0
    energies = dict(summary.per_inverter_wh)
    assert energies["INV-A"] == 2000.0
    formatted = svc.format_summary(summary)
    assert "Daily production for 2024-06-01:" in formatted
    assert "Site total (Modbus): 3.50 kWh" in formatted
    assert not svc.should_run(today, info)
