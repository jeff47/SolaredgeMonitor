# solaredge_monitor/services/notifiers/pushover.py

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Iterable

from solaredge_monitor.config import PushoverConfig
from solaredge_monitor.services.alert_logic import Alert


class PushoverNotifier:
    """Minimal Pushover client with helpful logging and validation."""

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, cfg: PushoverConfig, log):
        self.cfg = cfg
        self.log = log
        self._enabled = bool(cfg.enabled and cfg.token and cfg.user)

    # ------------------------------------------------------------------
    def _post(self, title: str, message: str, priority: int = 0) -> bool:
        if not self._enabled:
            self.log.debug("[Pushover] Disabled; skipping message: %s", title)
            return False

        data = urllib.parse.urlencode(
            {
                "token": self.cfg.token,
                "user": self.cfg.user,
                "title": title,
                "message": message,
                "priority": priority,
            }
        ).encode("utf-8")

        req = urllib.request.Request(self.API_URL, data=data)

        try:
            urllib.request.urlopen(req, timeout=10)
            self.log.info("[Pushover] Sent notification: %s", title)
            return True
        except urllib.error.URLError as exc:
            self.log.warning("[Pushover] Failed to send message: %s", exc)
            return False

    # ------------------------------------------------------------------
    def send_alerts(self, alerts: Iterable[Alert]) -> None:
        for alert in alerts:
            message = (
                f"{alert.inverter_name}: status={alert.status}, "
                f"PAC={alert.pac_w or 0:.0f} W — {alert.message}"
            )
            self._post("SolarEdge Alert", message)

    # ------------------------------------------------------------------
    def send_test(self) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"Test message from SolarEdge monitor at {timestamp}"
        self._post("SolarEdge Monitor Test", msg)
