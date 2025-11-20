# solaredge_monitor/services/output_formatter.py

from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional, Tuple

from solaredge_monitor.services.se_api_client import CloudInverter
from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.models.weather import WeatherEstimate

SnapshotItem = Tuple[str, Optional[InverterSnapshot]]


def _cloud_record(serial: Optional[str], cloud_by_serial: Mapping[str, CloudInverter]) -> Optional[CloudInverter]:
    if not serial or not cloud_by_serial:
        return None
    inv = cloud_by_serial.get(serial) or cloud_by_serial.get(serial.upper())
    return inv


def _cloud_status(serial: Optional[str], cloud_by_serial: Mapping[str, CloudInverter]) -> Optional[str]:
    inv = _cloud_record(serial, cloud_by_serial)
    return inv.status if inv else None


def _weather_to_dict(weather: WeatherEstimate | None) -> Optional[dict]:
    if weather is None:
        return None
    snap = weather.snapshot
    payload = {
        "timestamp": snap.timestamp.isoformat(),
        "provider": snap.provider,
        "cloud_cover_pct": snap.cloud_cover_pct,
        "temp_c": snap.temp_c,
        "wind_mps": snap.wind_mps,
        "ghi_wm2": snap.ghi_wm2,
        "dni_wm2": snap.dni_wm2,
        "diffuse_wm2": snap.diffuse_wm2,
        "sun_azimuth_deg": snap.sun_azimuth_deg,
        "sun_elevation_deg": snap.sun_elevation_deg,
        "source_latitude": snap.source_latitude,
        "source_longitude": snap.source_longitude,
        "error": snap.error,
    }
    per_inv = {}
    for name, inv in (weather.per_inverter or {}).items():
        per_inv[name] = {
            "expected_dc_kw": inv.expected_dc_kw,
            "expected_ac_kw": inv.expected_ac_kw,
            "poa_wm2": inv.poa_wm2,
            "module_temp_c_est": inv.module_temp_c_est,
            "temp_factor": inv.temp_factor,
            "array_kw_dc": inv.array_kw_dc,
            "ac_capacity_kw": inv.ac_capacity_kw,
            "dc_ac_derate": inv.dc_ac_derate,
            "cos_incidence": inv.cos_incidence,
            "tilt_deg": inv.tilt_deg,
            "azimuth_deg": inv.azimuth_deg,
            "albedo": inv.albedo,
            "noct_c": inv.noct_c,
            "temp_coeff_per_c": inv.temp_coeff_per_c,
        }
    payload["per_inverter"] = per_inv
    return payload


def emit_json(
    snapshot_items: Iterable[SnapshotItem],
    cloud_by_serial: Mapping[str, CloudInverter],
    *,
    weather_estimate: WeatherEstimate | None = None,
) -> None:
    payload = []
    for name, snapshot in snapshot_items:
        if snapshot is None:
            payload.append({"name": name, "error": "No Modbus data"})
            continue
        cloud_record = _cloud_record(snapshot.serial, cloud_by_serial)
        payload.append(
            {
                "name": snapshot.name,
                "serial": snapshot.serial,
                "model": snapshot.model,
                "status": snapshot.status,
                "cloud_status": cloud_record.status if cloud_record else None,
                "pac_w": snapshot.pac_w,
                "vdc_v": snapshot.vdc_v,
                "idc_a": snapshot.idc_a,
                "optimizers": (
                    cloud_record.connected_optimizers if cloud_record else None
                ),
                "error": snapshot.error,
            }
        )
    result = {"inverters": payload}
    weather_payload = _weather_to_dict(weather_estimate)
    if weather_payload is not None:
        result["weather"] = weather_payload
    print(json.dumps(result, indent=2))


def _format_weather_human(weather: WeatherEstimate, snapshot_items: Iterable[SnapshotItem]) -> list[str]:
    if weather is None:
        return []
    snap = weather.snapshot
    parts = []
    if snap.cloud_cover_pct is not None:
        parts.append(f"clouds={snap.cloud_cover_pct:.0f}%")
    if snap.temp_c is not None:
        parts.append(f"temp={snap.temp_c:.1f}C")
    if snap.wind_mps is not None:
        parts.append(f"wind={snap.wind_mps:.1f}m/s")
    if snap.ghi_wm2 is not None:
        parts.append(f"GHI={snap.ghi_wm2:.0f}W/m2")
    desc = " ".join(parts) if parts else "n/a"
    header = [f"Weather ({snap.provider}) @ {snap.timestamp.isoformat()}: {desc}"]

    pac_map = {}
    for name, snap_item in snapshot_items:
        if snap_item and snap_item.pac_w is not None:
            pac_map[name] = snap_item.pac_w / 1000.0

    lines = header
    for name, inv in sorted(weather.per_inverter.items()):
        exp = inv.expected_ac_kw
        actual_kw = pac_map.get(name)
        if exp is None and actual_kw is None:
            continue
        poa_txt = f"poa={inv.poa_wm2:.0f}W/m2" if inv.poa_wm2 is not None else "poa=n/a"
        parts = [f"[{name}] expected={exp:.2f}kW" if exp is not None else f"[{name}] expected=n/a"]
        if actual_kw is not None:
            parts.append(f"actual={actual_kw:.2f}kW")
        parts.append(poa_txt)
        lines.append(" ".join(parts))
    return lines


def emit_human(
    snapshot_items: Iterable[SnapshotItem],
    cloud_by_serial: Mapping[str, CloudInverter],
    *,
    weather_estimate: WeatherEstimate | None = None,
) -> None:
    if weather_estimate:
        for line in _format_weather_human(weather_estimate, snapshot_items):
            print(line)
    for name, snapshot in snapshot_items:
        if snapshot is None:
            print(f"[{name}] OFFLINE: no Modbus data")
            continue
        if snapshot.error:
            print(f"[{name}] ERROR: {snapshot.error}")
            continue

        cloud_status = _cloud_status(snapshot.serial, cloud_by_serial)
        cloud_txt = f" cloud={cloud_status}" if cloud_status is not None else ""

        cloud_rec = _cloud_record(snapshot.serial, cloud_by_serial)
        optimizers_txt = (
            f" optimizers={cloud_rec.connected_optimizers}"
            if cloud_rec and cloud_rec.connected_optimizers is not None
            else ""
        )

        print(
            f"[{name}] PAC={snapshot.pac_w or 0:.0f}W  "
            f"Vdc={snapshot.vdc_v or 0:.1f}V  Idc={snapshot.idc_a or 0:.1f}A  "
            f"status={snapshot.status}{cloud_txt}{optimizers_txt}"
        )
