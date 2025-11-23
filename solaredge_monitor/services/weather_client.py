from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional
import math

import requests
from zoneinfo import ZoneInfo

try:
    from astral import Observer
    from astral.sun import azimuth, elevation
except ImportError:  # pragma: no cover - optional dependency
    Observer = None
    azimuth = None
    elevation = None

from solaredge_monitor.config import InverterConfig, WeatherConfig
from solaredge_monitor.models.weather import (
    InverterExpectation,
    WeatherEstimate,
    WeatherSnapshot,
)


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _parse_time(ts: str | None, tz: ZoneInfo) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _nearest_index(times: list[str], target: datetime, tz: ZoneInfo) -> Optional[int]:
    if not times:
        return None
    target_local = target.astimezone(tz)
    parsed = [_parse_time(t, tz) for t in times]
    deltas = []
    for idx, dt in enumerate(parsed):
        if dt is None:
            deltas.append((idx, float("inf")))
        else:
            deltas.append((idx, abs((dt - target_local).total_seconds())))
    deltas.sort(key=lambda x: x[1])
    return deltas[0][0] if deltas else None


def _poa_irradiance(
    dni: float | None,
    diffuse: float | None,
    ghi: float | None,
    tilt_deg: float,
    azimuth_deg: float,
    sun_az_deg: float | None,
    sun_el_deg: float | None,
    albedo: float,
) -> tuple[Optional[float], Optional[float]]:
    """Return (poa, cos_incidence)."""
    if sun_el_deg is None or sun_az_deg is None:
        return None, None
    # Treat sun below the horizon as dark: do not synthesize production off twilight diffuse.
    if sun_el_deg <= 0:
        return 0.0, 0.0
    if diffuse is None or ghi is None:
        return None, None

    tilt = math.radians(tilt_deg)
    panel_az = math.radians(azimuth_deg)
    alt = math.radians(sun_el_deg)
    az = math.radians(sun_az_deg)

    cos_inc = (
        (math.sin(alt) * math.cos(tilt))
        + (math.cos(alt) * math.sin(tilt) * math.cos(az - panel_az))
    )
    if cos_inc < 0:
        cos_inc = 0.0

    beam = (dni or 0.0) * cos_inc
    diffuse_term = diffuse * (1 + math.cos(tilt)) / 2.0
    ground_term = ghi * albedo * (1 - math.cos(tilt)) / 2.0
    poa = beam + diffuse_term + ground_term
    return poa, cos_inc


def _module_temp(poa_wm2: float, ambient_c: float, noct_c: float) -> float:
    # Simple NOCT-based estimate: delta proportional to irradiance above 200 W/m² baseline.
    return ambient_c + (poa_wm2 / 800.0) * (noct_c - 20.0)


def _temp_factor(module_temp_c: float, coeff: float) -> float:
    factor = 1 + coeff * (module_temp_c - 25.0)
    return max(0.75, min(1.0, factor))


def _resolve_per_inverter_capacity(
    inverter_cfgs: Iterable[InverterConfig],
    site_default: float | None,
    attr: str,
) -> dict[str, Optional[float]]:
    values: dict[str, Optional[float]] = {}
    provided_total = 0.0
    missing: list[InverterConfig] = []

    for inv in inverter_cfgs:
        value = getattr(inv, attr)
        if value is not None:
            values[inv.name] = value
            provided_total += value
        else:
            missing.append(inv)

    if site_default is None or not missing:
        for inv in missing:
            values[inv.name] = None
        return values

    remaining = max(site_default - provided_total, 0.0)
    share = remaining / len(missing) if missing else 0.0
    for inv in missing:
        values[inv.name] = share if share > 0 else None
    return values


@dataclass
class WeatherClient:
    cfg: WeatherConfig
    log: any
    session: Optional[requests.Session] = None

    def __post_init__(self):
        if self.session is None:
            self.session = requests.Session()

    def _coords(self, fallback_lat: float | None, fallback_lon: float | None) -> tuple[float | None, float | None]:
        lat = self.cfg.latitude if self.cfg.latitude is not None else fallback_lat
        lon = self.cfg.longitude if self.cfg.longitude is not None else fallback_lon
        return lat, lon

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled and (self.cfg.provider or "open-meteo"))

    def fetch(
        self,
        now: datetime,
        inverter_cfgs: Iterable[InverterConfig],
        *,
        fallback_lat: float | None = None,
        fallback_lon: float | None = None,
    ) -> Optional[WeatherEstimate]:
        if not self.enabled:
            return None

        lat, lon = self._coords(fallback_lat, fallback_lon)
        if lat is None or lon is None:
            self.log.warning("Weather enabled but no latitude/longitude configured; skipping weather fetch.")
            return None

        tz = now.tzinfo or ZoneInfo("UTC")

        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(
                [
                    "shortwave_radiation",
                    "direct_radiation",
                    "diffuse_radiation",
                    "direct_normal_irradiance",
                    "temperature_2m",
                    "cloud_cover",
                    "wind_speed_10m",
                ]
            ),
            "current": "temperature_2m,weather_code,cloud_cover",
            "timezone": "auto",
            "forecast_days": 1,
        }

        try:
            resp = self.session.get(OPEN_METEO_URL, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # pragma: no cover - network errors
            self.log.warning("Weather fetch failed: %s", exc)
            return None

        try:
            tzname = data.get("timezone") or "UTC"
            tz = ZoneInfo(tzname)
        except Exception:
            tz = ZoneInfo("UTC")

        current = data.get("current", {}) or {}
        hourly = data.get("hourly", {}) or {}
        times = list(hourly.get("time", []) or [])
        idx = _nearest_index(times, now, tz)

        def _get(series, default=None):
            if idx is None or series is None or idx >= len(series):
                return default
            return series[idx]

        ghi = _get(hourly.get("shortwave_radiation"))
        dni = _get(hourly.get("direct_normal_irradiance"))
        diffuse = _get(hourly.get("diffuse_radiation"))
        temp_c = _get(hourly.get("temperature_2m"), current.get("temperature_2m"))
        cloud = current.get("cloud_cover")
        wind = _get(hourly.get("wind_speed_10m"))
        weather_code = current.get("weather_code")
        matched_series_time = _parse_time(times[idx], tz) if idx is not None and idx < len(times) else None

        current_time = _parse_time(current.get("time"), tz) or now.astimezone(tz)

        sun_az = sun_el = None
        if Observer and azimuth and elevation:
            try:
                obs = Observer(latitude=lat, longitude=lon)
                sun_az = azimuth(obs, current_time)
                sun_el = elevation(obs, current_time)
            except Exception:
                sun_az = sun_el = None

        snapshot = WeatherSnapshot(
            timestamp=current_time,
            source_series_time=matched_series_time,
            cloud_cover_pct=float(cloud) if cloud is not None else None,
            temp_c=float(temp_c) if temp_c is not None else None,
            wind_mps=float(wind) if wind is not None else None,
            ghi_wm2=float(ghi) if ghi is not None else None,
            dni_wm2=float(dni) if dni is not None else None,
            diffuse_wm2=float(diffuse) if diffuse is not None else None,
            weather_code=int(weather_code) if weather_code is not None else None,
            sun_azimuth_deg=float(sun_az) if sun_az is not None else None,
            sun_elevation_deg=float(sun_el) if sun_el is not None else None,
            provider=self.cfg.provider or "open-meteo",
            source_latitude=lat,
            source_longitude=lon,
        )

        per_inv_array = _resolve_per_inverter_capacity(inverter_cfgs, self.cfg.array_kw_dc, "array_kw_dc")
        per_inv_ac_cap = _resolve_per_inverter_capacity(inverter_cfgs, self.cfg.ac_capacity_kw, "ac_capacity_kw")

        estimates: dict[str, InverterExpectation] = {}
        for inv in inverter_cfgs:
            tilt = inv.tilt_deg if inv.tilt_deg is not None else self.cfg.tilt_deg
            az = inv.azimuth_deg if inv.azimuth_deg is not None else self.cfg.azimuth_deg
            array_kw = per_inv_array.get(inv.name)
            ac_cap = per_inv_ac_cap.get(inv.name)

            poa = cos_inc = None
            if snapshot.dni_wm2 is not None or snapshot.diffuse_wm2 is not None or snapshot.ghi_wm2 is not None:
                poa, cos_inc = _poa_irradiance(
                    snapshot.dni_wm2,
                    snapshot.diffuse_wm2,
                    snapshot.ghi_wm2,
                    tilt,
                    az,
                    snapshot.sun_azimuth_deg,
                    snapshot.sun_elevation_deg,
                    self.cfg.albedo,
                )

            expected_dc = expected_ac = module_temp = temp_factor = None
            if poa is not None and snapshot.temp_c is not None and array_kw is not None:
                module_temp = _module_temp(poa, snapshot.temp_c, self.cfg.noct_c)
                temp_factor = _temp_factor(module_temp, self.cfg.temp_coeff_per_c)
                expected_dc = array_kw * (poa / 1000.0) * temp_factor
                expected_ac = expected_dc * self.cfg.dc_ac_derate
                if ac_cap is not None:
                    expected_ac = min(expected_ac, ac_cap)
                expected_ac = max(0.0, expected_ac)

            estimates[inv.name] = InverterExpectation(
                name=inv.name,
                expected_dc_kw=expected_dc,
                expected_ac_kw=expected_ac,
                poa_wm2=poa,
                cos_incidence=cos_inc,
                module_temp_c_est=module_temp,
                temp_factor=temp_factor,
                array_kw_dc=array_kw,
                ac_capacity_kw=ac_cap,
                dc_ac_derate=self.cfg.dc_ac_derate,
                tilt_deg=tilt,
                azimuth_deg=az,
                albedo=self.cfg.albedo,
                noct_c=self.cfg.noct_c,
                temp_coeff_per_c=self.cfg.temp_coeff_per_c,
            )

        return WeatherEstimate(snapshot=snapshot, per_inverter=estimates)
