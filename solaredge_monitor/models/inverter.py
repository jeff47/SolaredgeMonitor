from dataclasses import dataclass
from datetime import datetime

@dataclass
class InverterSnapshot:
    serial: str
    name: str
    pac_w: float
    vdc: float
    idc: float
    status: str      # Producing, Sleeping, Fault, etc.
    timestamp: datetime
