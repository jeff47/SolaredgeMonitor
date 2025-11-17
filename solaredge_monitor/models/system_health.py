# solaredge_monitor/models/system_health.py
from dataclasses import dataclass
from typing import Optional, Dict
from solaredge_monitor.models.inverter import InverterSnapshot


@dataclass
class InverterHealth:
    name: str
    inverter_ok: bool
    reason: Optional[str]
    reading: Optional[InverterSnapshot]


@dataclass
class SystemHealth:
    system_ok: bool
    per_inverter: Dict[str, InverterHealth]
    reason: Optional[str]
