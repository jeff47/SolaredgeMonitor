# solaredge_monitor/services/notification_manager.py

from solaredge_monitor.config import PushoverConfig, HealthchecksConfig
from solaredge_monitor.services.alert_logic import Alert
from .notifiers.pushover import PushoverNotifier
from .notifiers.healthchecks import HealthchecksNotifier


class NotificationManager:
    def __init__(
        self,
        pushover_cfg: PushoverConfig,
        hc_cfg: HealthchecksConfig,
        log,
    ):
        self.pushover = PushoverNotifier(pushover_cfg, log)
        self.healthchecks = HealthchecksNotifier(hc_cfg, log)
        self.log = log

    def handle_alerts(self, alerts: list[Alert]):
        """
        For now:
          - If any alerts: send via Pushover and ping HC failure.
          - If no alerts: ping HC success.
        """
        if alerts:
            self.log.warning(f"{len(alerts)} alerts detected.")
            self.pushover.send_alerts(alerts)
            self.healthchecks.ping_failure()
        else:
            self.log.info("No alerts detected.")
            self.healthchecks.ping_success()
