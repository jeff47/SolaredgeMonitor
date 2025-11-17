# tests/fake_reader.py

from datetime import datetime
from solaredge_monitor.models.inverter import InverterSnapshot


class FakeInverterReader:
    """
    Generic fake reader for tests.
    Produces InverterSnapshot objects compatible with the real model.
    """

    def __init__(self, values_by_inverter: dict[str, dict], log):
        self.values = values_by_inverter
        self.log = log

    def read_all(self) -> dict[str, InverterSnapshot | None]:
        snapshots = {}
        now = datetime.now()

        for name, vals in self.values.items():
            if vals is None:
                snapshots[name] = None
                continue

            snapshots[name] = InverterSnapshot(
                name=name,
                serial=vals.get("serial", f"SIM-{name}"),
                model=vals.get("model", "SIMMODEL"),
                status=vals.get("status", 4),
                vendor_status=vals.get("vendor_status"),
                pac_w=vals.get("pac_w"),
                vdc_v=vals.get("vdc_v"),
                idc_a=vals.get("idc_a"),
                error=vals.get("error"),
                timestamp=vals.get("timestamp", now),
            )
        return snapshots



class MockModbusReader(FakeInverterReader):
    pass
