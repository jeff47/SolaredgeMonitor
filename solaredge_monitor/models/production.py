from dataclasses import dataclass

@dataclass
class ProductionStats:
    date: str
    total_wh: float
    per_inverter_wh: dict
