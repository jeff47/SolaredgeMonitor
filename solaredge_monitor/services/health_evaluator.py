# solaredge_monitor/services/health_evaluator.py

from __future__ import annotations
from typing import Dict, Optional, Any

from solaredge_monitor.config import HealthConfig
from solaredge_monitor.models.system_health import InverterHealth, SystemHealth
from solaredge_monitor.models.inverter import InverterSnapshot


class HealthEvaluator:
    """
    Modbus-only health evaluator including per-inverter checks and
    peer comparison. Peer-threshold parameters come from config.
    """

    STATUS_MAP = {
        1: "Off",
        2: "Sleeping",
        3: "Starting",
        4: "Producing",
        5: "Throttled",
        6: "Shutting Down",
        7: "Fault",
        8: "Standby",
    }

    def __init__(self, cfg_health: HealthConfig, log: Any):
        self.cfg = cfg_health
        self.log = log

    # ----------------------------------------------------------------------
    # Per-inverter evaluation
    # ----------------------------------------------------------------------

    def evaluate_inverter(self, name: str, reading: Optional[InverterSnapshot]) -> InverterHealth:
        """Evaluate a single inverter from its Modbus reading."""
        if reading is None:
            return InverterHealth(
                name=name,
                inverter_ok=False,
                reason="No Modbus data (offline?)",
                reading=None,
            )

        status = reading.status
        status_str = self.STATUS_MAP.get(status, f"Unknown({status})")

        # ---------------------------------------
        # Abnormal statuses (ALWAYS unhealthy)
        # ---------------------------------------
        if status in (2, 3, 6):   # Sleeping, Starting, Shutting Down
            return InverterHealth(
                name=name,
                inverter_ok=False,
                reason=f"Unexpected inverter status: {status_str}",
                reading=reading,
            )

        # ---------------------------------------
        # Fault
        # ---------------------------------------
        if status == 7:
            return InverterHealth(
                name=name,
                inverter_ok=False,
                reason=f"Fault state ({status_str})",
                reading=reading,
            )

        # ---------------------------------------
        # Producing but extremely low PAC (<10W)
        # ---------------------------------------
        if status == 4 and reading.pac_w is not None and reading.pac_w < 10:
            return InverterHealth(
                name=name,
                inverter_ok=False,
                reason=f"Producing but PAC={reading.pac_w:.1f} W",
                reading=reading,
            )

        # ---------------------------------------
        # Low Vdc (<50V)
        # ---------------------------------------
        if reading.vdc_v is not None and reading.vdc_v < 50:
            return InverterHealth(
                name=name,
                inverter_ok=False,
                reason=f"Low DC voltage Vdc={reading.vdc_v:.1f} V",
                reading=reading,
            )

        # ---------------------------------------
        # Healthy
        # ---------------------------------------
        return InverterHealth(
            name=name,
            inverter_ok=True,
            reason=None,
            reading=reading,
        )


    # ----------------------------------------------------------------------
    # Peer comparison
    # ----------------------------------------------------------------------

    def _peer_compare(self, per_inverter: Dict[str, InverterHealth]) -> None:
        pac_values = [
            (state.name, state.reading.pac_w)
            for state in per_inverter.values()
            if state.inverter_ok
            and state.reading is not None
            and state.reading.status == 4
            and state.reading.pac_w is not None
        ]

        if len(pac_values) < 2:
            return

        pac_nums = [p[1] for p in pac_values]
        max_pac = max(pac_nums)
        min_pac = min(pac_nums)

        # ---------------------------------------------
        # LOW-LIGHT SUPPRESSION of peer comparison
        # ---------------------------------------------
        if max_pac < self.cfg.low_light_peer_skip_threshold:
            # Don't compare peers at very low light
            return

        # ---------------------------------------------
        # HIGH-POWER PEER COMPARISON
        # ---------------------------------------------
        min_prod = self.cfg.min_production_for_peer_check
        if max_pac < min_prod:
            return  # skip entirely

        ratio_threshold = self.cfg.peer_ratio_threshold
        ratio = min_pac / max_pac if max_pac > 0 else 1.0

        if ratio >= ratio_threshold:
            return

        # Flag the lowest PAC inverter(s)
        for name, pac in pac_values:
            if pac == min_pac:
                inv = per_inverter[name]
                inv.inverter_ok = False
                inv.reason = (
                    f"Low output vs peer "
                    f"(PAC={pac:.1f} W, peer={max_pac:.1f} W, ratio={ratio:.2f} < {ratio_threshold})"
                )
                self.log.debug(f"Peer comparison flagged {name} as low")

    # ----------------------------------------------------------------------
    # System-level evaluation
    # ----------------------------------------------------------------------
    def _clear_pac_related_flags(self, per_inverter: Dict[str, InverterHealth]) -> None:
        for inv_state in per_inverter.values():
            if inv_state.inverter_ok:
                continue
            reason = (inv_state.reason or "").lower()
            if "pac" in reason or "peer" in reason:
                inv_state.inverter_ok = True
                inv_state.reason = None

    def evaluate(self, readings: Dict[str, InverterSnapshot], low_light_grace: bool = False) -> SystemHealth:
        # --------------------------------------------------------------
        # 1. FIRST: per-inverter checks (never skipped)
        # --------------------------------------------------------------
        per_inverter = {
            name: self.evaluate_inverter(name, reading)
            for name, reading in readings.items()
        }

        # If any inverter has a NON-producing status (2,3,5,6,7),
        # low-light/cloudy logic must NOT override it.
        abnormal_status_present = any(
            inv.reading and inv.reading.status not in (4,)
            for inv in per_inverter.values()
        )

        # Extract producing-only readings
        producing = [
            inv.reading for inv in per_inverter.values()
            if inv.reading is not None and inv.reading.status == 4
        ]

        # --------------------------------------------------------------
        # 2. CLOUDY OVERRIDE (applies only when *all* inverters are producing)
        # --------------------------------------------------------------
        if producing and not abnormal_status_present:
            threshold = self.cfg.low_light_peer_skip_threshold  # ex: 20W

            all_low = all(
                r.pac_w is not None and r.pac_w < threshold
                for r in producing
            )

            if all_low:
                # Reset inverter_ok for PAC-related issues only
                for inv_state in per_inverter.values():
                    if inv_state.inverter_ok is False and inv_state.reason and "PAC" in inv_state.reason:
                        inv_state.inverter_ok = True
                        inv_state.reason = None

                # Return early: cloudy = healthy
                bad = [i for i in per_inverter.values() if not i.inverter_ok]
                if not bad:
                    return SystemHealth(
                        system_ok=True,
                        per_inverter=per_inverter,
                        reason=None,
                    )

        # --------------------------------------------------------------
        # 3. LOW-LIGHT ASYMMETRY SUPPRESSION (peer compare skip)
        # --------------------------------------------------------------
        if producing and not abnormal_status_present:
            pac_values = [r.pac_w for r in producing if r.pac_w is not None]
            if pac_values and max(pac_values) < self.cfg.low_light_peer_skip_threshold:
                # Don’t do peer comparison
                bad = [i for i in per_inverter.values() if not i.inverter_ok]
                system_ok = len(bad) == 0
                return SystemHealth(
                    system_ok=system_ok,
                    per_inverter=per_inverter,
                    reason=None if system_ok else "; ".join(f"{b.name}: {b.reason}" for b in bad)
                )

        # --------------------------------------------------------------
        # 4. Full peer comparison
        # --------------------------------------------------------------
        self._peer_compare(per_inverter)

        if low_light_grace:
            self._clear_pac_related_flags(per_inverter)

        # --------------------------------------------------------------
        # 5. Aggregate system health
        # --------------------------------------------------------------
        bad = [s for s in per_inverter.values() if not s.inverter_ok]

        if bad:
            return SystemHealth(
                system_ok=False,
                per_inverter=per_inverter,
                reason="; ".join(f"{b.name}: {b.reason}" for b in bad),
            )

        return SystemHealth(
            system_ok=True,
            per_inverter=per_inverter,
            reason=None,
        )



