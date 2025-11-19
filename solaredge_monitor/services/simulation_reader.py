# solaredge_monitor/services/simulation_reader.py

from datetime import datetime
from ..models.inverter import InverterSnapshot


class SimulationReader:
    """
    Simulation Modbus reader using the unified [simulation] config format.
    """

    def __init__(self, fault_type, cfg, log):
        self.fault = fault_type
        self.cfg_root = cfg or {}
        self.scenario_cfg = self.cfg_root.get(fault_type, {}) if fault_type else {}
        self.log = log

    # --------------------------------------------------------------
    # Shared parser (same as API simulation)
    # --------------------------------------------------------------
    @staticmethod
    def parse_kv_list(raw):
        if not raw:
            return {}
        out = {}
        for item in raw.split(","):
            if ":" in item:
                k, v = item.split(":", 1)
                out[k.strip()] = float(v.strip())
        return out

    @staticmethod
    def parse_list(raw):
        if not raw:
            return []
        return [x.strip() for x in raw.split(",") if x.strip()]

    # Unified getter (scenario → root → None)
    def _get_map(self, key):
        if key in self.scenario_cfg:
            return self.parse_kv_list(self.scenario_cfg[key])
        if key in self.cfg_root:
            return self.parse_kv_list(self.cfg_root[key])
        return {}

    def _get_list(self, key):
        if key in self.scenario_cfg:
            return self.parse_list(self.scenario_cfg[key])
        if key in self.cfg_root:
            return self.parse_list(self.cfg_root[key])
        return []

    # --------------------------------------------------------------
    # Main: produce simulated Modbus snapshots
    # --------------------------------------------------------------
    def read_all(self):
        now = datetime.now()

        inv_ids = self._get_list("inverters")

        status_map = self._get_map("inverter_status")
        pac_map    = self._get_map("inverter_pac_w")
        vdc_map    = self._get_map("inverter_vdc")
        idc_map    = self._get_map("inverter_idc")
        total_map  = self._get_map("inverter_total_wh")

        snapshots = []

        for inv in inv_ids:
            status = status_map.get(inv, 0)           # integer codes or map to strings later
            pac    = pac_map.get(inv, 0.0)
            vdc    = vdc_map.get(inv, 0.0)
            idc    = idc_map.get(inv, 0.0)
            total  = total_map.get(inv)

            self.log.debug(
                f"[SIM-MODBUS] {inv}: status={status}, pac={pac}, "
                f"vdc={vdc}, idc={idc}"
            )

            snapshots.append(
                InverterSnapshot(
                    serial=inv,
                    name=inv,
                    model="SIM",
                    status=int(status),
                    vendor_status=None,
                    pac_w=float(pac),
                    vdc_v=float(vdc),
                    idc_a=float(idc),
                    total_wh=float(total) if total is not None else None,
                    error=None,
                    timestamp=now,
                )
            )

        return snapshots
