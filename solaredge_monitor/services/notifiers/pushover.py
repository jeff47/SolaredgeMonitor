# solaredge_monitor/services/notifiers/pushover.py

import urllib.request
import urllib.parse
import urllib.error
import sys
from datetime import datetime
from solaredge_monitor.config import PushoverConfig
from solaredge_monitor.services.alert_logic import Alert


class PushoverNotifier:
    def __init__(self, cfg: PushoverConfig, log):
        self.cfg = cfg
        self.log = log

    def send_alerts(self, alerts: list[Alert]):
        if not self.cfg.enabled:
            return
        if not self.cfg.token or not self.cfg.user:
            self.log.warning("[Pushover] Not configured (missing token/user)")
            return

        for a in alerts:
            msg = f"{a.inverter_name} offline. (PAC={a.pac_w or 0:.0f}W, status={a.status})"
            # For now use fixed title
            title = "SolarEdge Alert"

            data = urllib.parse.urlencode(
                {
                    "token": self.cfg.token,
                    "user": self.cfg.user,
                    "title": title,
                    "message": msg,
                    # Could add priority, sound, etc.
                }
            ).encode("utf-8")

            try:
                req = urllib.request.Request(
                    "https://api.pushover.net/1/messages.json", data=data
                )
                urllib.request.urlopen(req, timeout=10)
                self.log.info(f"[Pushover] Sent alert: {msg}")
            except Exception as e:
                print(f"⚠️ Failed to send Pushover alert: {e}", file=sys.stderr)

    def send_test(self):
        if not self.cfg.enabled:
            return
        msg = (
            "Test message from SolarEdge monitor\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        # Could reuse send_alerts with a pseudo-Alert, left simple for now.
