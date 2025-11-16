from dataclasses import dataclass

@dataclass
class OptimizerStatus:
    optimizer_id: str
    inverter_serial: str
    last_seen: str
    status: str
