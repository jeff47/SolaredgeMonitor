from dataclasses import dataclass
from datetime import datetime


@dataclass
class DaylightInfo:
    is_daylight: bool
    phase: str  # NIGHT, DAY, SUNRISE_GRACE, SUNSET_GRACE
    sunrise: datetime
    sunrise_grace_end: datetime
    sunset: datetime
    sunset_grace_start: datetime
    production_over_at: datetime
    in_grace_window: bool
    skip_modbus: bool
    production_day_over: bool
