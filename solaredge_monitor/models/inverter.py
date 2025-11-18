# solaredge_monitor/models/inverter.py
from dataclasses import dataclass
from datetime import datetime


@dataclass
class InverterSnapshot:
    name: str
    serial: str
    model: str
    status: int           # numeric SolarEdge status code
    vendor_status: str | None
    pac_w: float | None
    vdc_v: float | None
    idc_a: float | None
    total_wh: float | None
    error: str | None     # non-None if Modbus read failed
    timestamp: datetime
