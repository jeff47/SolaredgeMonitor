# solaredge_monitor/services/notifiers/pushover.py

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Iterable, Optional

from solaredge_monitor.config import PushoverConfig
from solaredge_monitor.services.alert_logic import Alert
from solaredge_monitor.models.system_health import SystemHealth, InverterHealth


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
    def _select_baseline(self, alert: Alert, health: Optional[SystemHealth]) -> Optional[InverterHealth]:
        if not health:
            return None
        if alert.inverter_name == "SYSTEM":
            return None

        per_inv = health.per_inverter or {}
        if not per_inv:
            return None

        candidates = [
            inv
            for name, inv in per_inv.items()
            if name != alert.inverter_name
            and inv.inverter_ok
            and inv.reading is not None
        ]
        if not candidates:
            return None

        def pac_value(inv: InverterHealth) -> float:
            reading = inv.reading
            if reading and reading.pac_w is not None:
                return reading.pac_w
            return -1.0

        return max(candidates, key=pac_value)

    def _format_baseline_line(self, baseline: InverterHealth) -> Optional[str]:
        reading = baseline.reading
        if reading is None:
            return None
        status = reading.status if reading.status is not None else "unknown"
        pac = reading.pac_w if reading.pac_w is not None else 0.0
        return f"Baseline {baseline.name}: status={status}, PAC={pac:.0f} W"

    def _format_alert_message(self, alert: Alert, health: Optional[SystemHealth]) -> str:
        pac = alert.pac_w if alert.pac_w is not None else 0.0
        lines = [
            f"{alert.inverter_name}: status={alert.status}, PAC={pac:.0f} W",
            f"Reason: {alert.message}",
        ]

        baseline = self._select_baseline(alert, health)
        if baseline:
            baseline_line = self._format_baseline_line(baseline)
            if baseline_line:
                lines.append(baseline_line)

        return "\n".join(lines)

    def send_alerts(self, alerts: Iterable[Alert], *, health: Optional[SystemHealth] = None) -> None:
        for alert in alerts:
            message = self._format_alert_message(alert, health)
            self._post("SolarEdge Alert", message)

    # ------------------------------------------------------------------
    def send_test(self) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"Test message from SolarEdge monitor at {timestamp}"
        self._post("SolarEdge Monitor Test", msg)

    # ------------------------------------------------------------------
    def send_message(self, title: str, message: str) -> None:
        self._post(title, message)
