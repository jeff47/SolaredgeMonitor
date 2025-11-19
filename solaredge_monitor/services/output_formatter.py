# solaredge_monitor/services/output_formatter.py

from __future__ import annotations

import json
from typing import Iterable, Mapping, Optional, Tuple

from solaredge_monitor.services.se_api_client import CloudInverter
from solaredge_monitor.models.inverter import InverterSnapshot

SnapshotItem = Tuple[str, Optional[InverterSnapshot]]


def _cloud_record(serial: Optional[str], cloud_by_serial: Mapping[str, CloudInverter]) -> Optional[CloudInverter]:
    if not serial or not cloud_by_serial:
        return None
    inv = cloud_by_serial.get(serial) or cloud_by_serial.get(serial.upper())
    return inv


def _cloud_status(serial: Optional[str], cloud_by_serial: Mapping[str, CloudInverter]) -> Optional[str]:
    inv = _cloud_record(serial, cloud_by_serial)
    return inv.status if inv else None


def emit_json(snapshot_items: Iterable[SnapshotItem], cloud_by_serial: Mapping[str, CloudInverter]) -> None:
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
    print(json.dumps({"inverters": payload}, indent=2))


def emit_human(snapshot_items: Iterable[SnapshotItem], cloud_by_serial: Mapping[str, CloudInverter]) -> None:
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
