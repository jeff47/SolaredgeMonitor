# solaredge_monitor/services/modbus_reader.py

from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Optional, Any

from solaredge_monitor.vendor.solaredge_modbus import Inverter as ModbusInverter
from solaredge_monitor.models.inverter import InverterSnapshot


# ============================================================================
# Scale helper
# ============================================================================

def apply_scale(value: Any, scale: Any) -> Optional[float]:
    if value is None or scale is None:
        return None
    try:
        return float(value) * (10 ** int(scale))
    except Exception:
        return None


# ============================================================================
# Modbus Reader
# ============================================================================

class ModbusReader:
    """
    Clean and reliable single-inverter Modbus reader, built from the known
    working alpha logic and adapted to your new config system.
    """

    def __init__(self, modbus_cfg: Any, log: Any):
        """
        modbus_cfg: ModbusConfig
            .inverters → list[InverterConfig]
            .retries
            .timeout

        log: logger interface
        """
        self.modbus_cfg = modbus_cfg
        self.log = log
        self.retries = modbus_cfg.retries
        self.timeout = modbus_cfg.timeout

    # ----------------------------------------------------------------------

    def _safe_read(self, client: ModbusInverter, key: str) -> Optional[Any]:
        """Read a single SunSpec key safely."""
        try:
            result = client.read(key)
            if not result:
                return None
            return list(result.values())[0]
        except Exception as e:
            self.log.debug(f"Modbus read error [{key}]: {e}")
            return None

    # ----------------------------------------------------------------------

    def read_inverter(self, inv_cfg) -> Optional[InverterSnapshot]:
        """
        Read one inverter using fields from InverterConfig:
            inv_cfg.name
            inv_cfg.host
            inv_cfg.port
            inv_cfg.unit
        """

        name = inv_cfg.name
        host = inv_cfg.host
        port = inv_cfg.port
        unit = inv_cfg.unit

        client = ModbusInverter(
            host=host,
            port=port,
            unit=unit,
            timeout=self.timeout,
            retries=self.retries,
        )

        try:
            if not client.connect():
                self.log.debug(f"{name}: modbus connect failed")
                return None

            # Identity
            serial = self._safe_read(client, "c_serialnumber")
            model  = self._safe_read(client, "c_model")

            # Telemetry
            status = self._safe_read(client, "status")

            pac    = self._safe_read(client, "power_ac")
            pac_s  = self._safe_read(client, "power_ac_scale")

            vdc    = self._safe_read(client, "voltage_dc")
            vdc_s  = self._safe_read(client, "voltage_dc_scale")

            idc    = self._safe_read(client, "current_dc")
            idc_s  = self._safe_read(client, "current_dc_scale")

            total    = self._safe_read(client, "energy_total")
            total_s  = self._safe_read(client, "energy_total_scale")

            now = datetime.now(timezone.utc)
            return InverterSnapshot(
                name=name,
                serial=serial or "unknown",
                model=model or "unknown",
                status=status or 0,
                vendor_status=None,
                pac_w=apply_scale(pac, pac_s),
                vdc_v=apply_scale(vdc, vdc_s),
                idc_a=apply_scale(idc, idc_s),
                total_wh=apply_scale(total, total_s),
                error=None,
                timestamp=now,
            )

        finally:
            try:
                client.disconnect()
            except Exception:
                pass

    # ----------------------------------------------------------------------

    def read_all(self) -> Dict[str, Optional[InverterSnapshot]]:
        results = {}

        for inv_cfg in self.modbus_cfg.inverters:
            name = inv_cfg.name

            self.log.debug(f"Modbus: reading inverter {name}")

            reading = self.read_inverter(inv_cfg)

            if reading:
                results[name] = reading
            else:
                self.log.debug(f"{name}: no data (offline?)")
                results[name] = None

        return results
