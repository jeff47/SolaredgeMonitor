from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


@dataclass
class WeatherSnapshot:
    timestamp: datetime
    source_series_time: Optional[datetime]
    cloud_cover_pct: Optional[float]
    temp_c: Optional[float]
    wind_mps: Optional[float]
    ghi_wm2: Optional[float]
    dni_wm2: Optional[float]
    diffuse_wm2: Optional[float]
    weather_code: Optional[int]
    sun_azimuth_deg: Optional[float]
    sun_elevation_deg: Optional[float]
    provider: str
    source_latitude: float
    source_longitude: float
    error: Optional[str] = None


@dataclass
class InverterExpectation:
    name: str
    expected_dc_kw: Optional[float]
    expected_ac_kw: Optional[float]
    poa_wm2: Optional[float]
    cos_incidence: Optional[float]
    module_temp_c_est: Optional[float]
    temp_factor: Optional[float]
    array_kw_dc: Optional[float]
    ac_capacity_kw: Optional[float]
    dc_ac_derate: Optional[float]
    tilt_deg: Optional[float]
    azimuth_deg: Optional[float]
    albedo: Optional[float]
    noct_c: Optional[float]
    temp_coeff_per_c: Optional[float]


@dataclass
class WeatherEstimate:
    snapshot: WeatherSnapshot
    per_inverter: Dict[str, InverterExpectation]
