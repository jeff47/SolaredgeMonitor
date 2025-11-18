# solaredge_monitor/services/notification_manager.py

from __future__ import annotations

from typing import Iterable, List

from solaredge_monitor.config import HealthchecksConfig, PushoverConfig
from solaredge_monitor.services.alert_logic import Alert
from solaredge_monitor.services.notifiers.healthchecks import HealthchecksNotifier
from solaredge_monitor.services.notifiers.pushover import PushoverNotifier


class NotificationManager:
    """Coordinates outbound notifications (Pushover + Healthchecks)."""

    def __init__(self, pushover_cfg: PushoverConfig, hc_cfg: HealthchecksConfig, log):
        self.log = log
        self.pushover = PushoverNotifier(pushover_cfg, log)
        self.healthchecks = HealthchecksNotifier(hc_cfg, log)

    # ------------------------------------------------------------------
    def handle_alerts(self, alerts: Iterable[Alert]) -> None:
        """Send notifications based on the current alert list."""

        alerts_list: List[Alert] = list(alerts)

        if not alerts_list:
            self.log.info("No alerts detected; sending Healthchecks success ping.")
            self.healthchecks.ping_success("system ok")
            return

        self.log.warning("%d alerts detected; notifying endpoints.", len(alerts_list))
        self.pushover.send_alerts(alerts_list)

        summary = ", ".join(f"{a.inverter_name}:{a.status}" for a in alerts_list)
        self.healthchecks.ping_failure(summary or "alerts present")

    # ------------------------------------------------------------------
    def send_test_notifications(self) -> None:
        """Trigger manual test messages for both channels."""

        self.log.info("Sending test notification via Pushover and Healthchecks...")
        self.pushover.send_test()
        self.healthchecks.send_test()

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
