from dataclasses import dataclass
from datetime import datetime

@dataclass
class DaylightInfo:
    is_daylight: bool
    phase: str  # NIGHT, DAY, MORNING_GRACE, EVENING_GRACE
    sunrise: datetime
    sunset: datetime
