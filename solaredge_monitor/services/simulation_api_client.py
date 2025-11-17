# solaredge_monitor/services/simulation_api_client.py

from datetime import datetime
from ..models.production import ProductionStats
from ..models.optimizer import OptimizerStatus


class SimulationAPIClient:
    """
    Simulation API client using unified [simulation] config format.
    """

    def __init__(self, fault_type, cfg, log):
        self.fault = fault_type
        self.cfg_root = cfg
        self.scenario_cfg = cfg.get(fault_type, {})
        self.log = log

    # Same parser utilities
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
    def parse_status_map(raw):
        if not raw:
            return {}
        out = {}
        for item in raw.split(","):
            if ":" in item:
                k, v = item.split(":", 1)
                out[k.strip()] = v.strip()
        return out

    def _get_map(self, key, numeric=True):
        raw = self.scenario_cfg.get(key) or self.cfg_root.get(key)
        if not raw:
            return {}
        return self.parse_kv_list(raw) if numeric else self.parse_status_map(raw)

    # ----------------------------------------------------------
    # Daily production
    # ----------------------------------------------------------
    def get_daily_production(self, date):
        per_inv = self._get_map("inverter_daily_wh", numeric=True)
        total = sum(per_inv.values())

        return ProductionStats(
            date=str(date),
            total_wh=total,
            per_inverter_wh=per_inv,
        )

    # ----------------------------------------------------------
    # Optimizer counts/states
    # ----------------------------------------------------------
    def get_optimizer_statuses(self):
        """
        Map inverter -> optimizer count OR statuses.
        """
        now = datetime.now().isoformat()
        opt_map = self._get_map("inverter_optimizers", numeric=True)

        # Convert counts into generic OptimizerStatus objects
        result = []
        for inv, count in opt_map.items():
            for i in range(int(count)):
                oid = f"{inv}-OPT-{i+1}"
                result.append(
                    OptimizerStatus(
                        optimizer_id=oid,
                        inverter_serial=inv,
                        last_seen=now,
                        status="active"
                    )
                )
        return result
