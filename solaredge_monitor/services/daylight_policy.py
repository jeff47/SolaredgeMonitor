from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

try:
    from astral import Observer
    from astral.sun import sun
except ImportError:  # pragma: no cover - optional dependency
    Observer = None
    sun = None

from solaredge_monitor.config import DaylightConfig
from solaredge_monitor.models.daylight import DaylightInfo


class DaylightPolicy:
    """Encapsulates sunrise/sunset logic with configurable grace windows."""

    def __init__(
        self,
        cfg: DaylightConfig,
        log,
        *,
        skip_modbus_at_night: bool = True,
        skip_cloud_at_night: bool = False,
    ):
        self.cfg = cfg
        self.log = log
        self._tz = ZoneInfo(cfg.timezone)
        self._observer = None
        self._skip_modbus_at_night = skip_modbus_at_night
        self._skip_cloud_at_night = skip_cloud_at_night

        if Observer and cfg.latitude is not None and cfg.longitude is not None:
            self._observer = Observer(latitude=cfg.latitude, longitude=cfg.longitude)

        self._static_sunrise = self._parse_time(cfg.static_sunrise) or time(6, 0)
        self._static_sunset = self._parse_time(cfg.static_sunset) or time(18, 0)

    @staticmethod
    def _parse_time(raw: str | None) -> time | None:
        if not raw:
            return None
        text = raw.strip()
        if not text:
            return None
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return time(hour=hour, minute=minute)

    def _sun_times(self, local_date) -> tuple[datetime, datetime]:
        if self._observer and sun:
            data = sun(self._observer, date=local_date, tzinfo=self._tz)
            sunrise = data["sunrise"]
            sunset = data["sunset"]
        else:
            sunrise = datetime.combine(local_date, self._static_sunrise, tzinfo=self._tz)
            sunset = datetime.combine(local_date, self._static_sunset, tzinfo=self._tz)

        if sunset <= sunrise:
            sunset = sunrise + timedelta(hours=12)

        return sunrise, sunset

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    def get_info(self, now: datetime) -> DaylightInfo:
        if now.tzinfo is None:
            self.log.warning(
                "DaylightPolicy received naive datetime; assuming %s timezone",
                self.cfg.timezone,
            )
            local_now = now.replace(tzinfo=self._tz)
        else:
            local_now = now.astimezone(self._tz)
        sunrise, sunset = self._sun_times(local_now.date())

        sunrise_grace_end = sunrise + timedelta(minutes=self.cfg.sunrise_grace_minutes)
        sunset_grace_start = sunset - timedelta(minutes=self.cfg.sunset_grace_minutes)
        if sunset_grace_start < sunrise_grace_end:
            sunset_grace_start = sunrise_grace_end

        production_over_at = sunset + timedelta(minutes=self.cfg.summary_delay_minutes)

        if local_now < sunrise:
            phase = "NIGHT"
        elif local_now < sunrise_grace_end:
            phase = "SUNRISE_GRACE"
        elif local_now < sunset_grace_start:
            phase = "DAY"
        elif local_now < sunset:
            phase = "SUNSET_GRACE"
        else:
            phase = "NIGHT"

        in_grace = phase in ("SUNRISE_GRACE", "SUNSET_GRACE")
        is_daylight = phase in ("SUNRISE_GRACE", "DAY", "SUNSET_GRACE")
        skip_modbus = phase == "NIGHT" and self._skip_modbus_at_night
        skip_cloud = phase == "NIGHT" and self._skip_cloud_at_night
        production_day_over = local_now >= production_over_at

        self.log.debug(
            "Daylight policy: phase=%s, sunrise=%s, sunset=%s",
            phase,
            sunrise,
            sunset,
        )

        return DaylightInfo(
            is_daylight=is_daylight,
            phase=phase,
            sunrise=sunrise,
            sunrise_grace_end=sunrise_grace_end,
            sunset=sunset,
            sunset_grace_start=sunset_grace_start,
            production_over_at=production_over_at,
            in_grace_window=in_grace,
            skip_modbus=skip_modbus,
            skip_cloud=skip_cloud,
            production_day_over=production_day_over,
        )
