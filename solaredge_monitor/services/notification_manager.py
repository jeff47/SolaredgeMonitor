# solaredge_monitor/services/notification_manager.py

from __future__ import annotations

from typing import Iterable, List, Optional

from solaredge_monitor.config import HealthchecksConfig, PushoverConfig
from solaredge_monitor.services.alert_logic import Alert
from solaredge_monitor.services.alert_state import RecoveryNotification
from solaredge_monitor.services.notifiers.healthchecks import HealthchecksNotifier
from solaredge_monitor.services.notifiers.pushover import PushoverNotifier
from solaredge_monitor.models.system_health import SystemHealth


class NotificationManager:
    """Coordinates outbound notifications (Pushover + Healthchecks)."""

    def __init__(self, pushover_cfg: PushoverConfig, hc_cfg: HealthchecksConfig, log):
        self.log = log
        self.pushover = PushoverNotifier(pushover_cfg, log)
        self.healthchecks = HealthchecksNotifier(hc_cfg, log)

    # ------------------------------------------------------------------
    def handle_alerts(
        self,
        alerts: Iterable[Alert],
        *,
        recoveries: Optional[Iterable[RecoveryNotification]] = None,
        health: Optional[SystemHealth] = None,
        has_active_health_incident: bool = False,
    ) -> None:
        """Send notifications based on the current alert list."""

        alerts_list: List[Alert] = list(alerts)
        recovery_list: List[RecoveryNotification] = list(recoveries or [])

        if recovery_list:
            self.log.info("%d recovery notifications detected.", len(recovery_list))
            self.pushover.send_recoveries(recovery_list)

        if not alerts_list:
            if health is None:
                # No health evaluation was performed (e.g. all inverters unreachable);
                # do not send a false success ping.
                return
            if not health.system_ok and has_active_health_incident:
                summary = self._health_failure_summary(health)
                self.log.warning(
                    "No new alerts emitted, but system health is still failing; sending Healthchecks failure ping."
                )
                self.healthchecks.ping_failure(summary)
                return

            self.log.debug("No alerts detected; sending Healthchecks success ping.")
            self.healthchecks.ping_success("system ok")
            return

        self.log.warning("%d alerts detected; notifying endpoints.", len(alerts_list))
        self.pushover.send_alerts(alerts_list, health=health)

        summary = ", ".join(f"{a.inverter_name}:{a.status}" for a in alerts_list)
        self.healthchecks.ping_failure(summary or "alerts present")

    def _health_failure_summary(self, health: SystemHealth) -> str:
        if health.reason:
            return health.reason
        failing = [
            name
            for name, inv in health.per_inverter.items()
            if not inv.inverter_ok
        ]
        if failing:
            return ", ".join(failing)
        return "health failure"

    # ------------------------------------------------------------------
    def send_daily_summary(
        self,
        summary_text: str,
        modbus_wh: float | None,
        api_wh: float | None,
    ) -> None:
        """Send the formatted daily summary via Pushover only."""
        if not summary_text:
            return
        title_wh = modbus_wh if modbus_wh is not None else api_wh or 0.0
        title = f"SolarEdge Daily Production: {title_wh / 1000.0:.2f} kWh"
        self.pushover.send_message(title, summary_text)
