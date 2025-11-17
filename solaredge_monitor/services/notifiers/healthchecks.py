# solaredge_monitor/services/notifiers/healthchecks.py

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from solaredge_monitor.config import HealthchecksConfig


class HealthchecksNotifier:
    """Lightweight Healthchecks.io client with optional messages."""

    def __init__(self, cfg: HealthchecksConfig, log):
        self.cfg = cfg
        self.log = log
        self._base_url = (cfg.ping_url or "").rstrip("/")
        self._enabled = bool(cfg.enabled and self._base_url)

    # ------------------------------------------------------------------
    def _hit(self, suffix: str = "", message: str = "") -> bool:
        if not self._enabled:
            self.log.debug("[Healthchecks] Disabled; skipping ping %s", suffix)
            return False

        url = f"{self._base_url}{suffix}" if suffix else self._base_url

        parsed = list(urllib.parse.urlparse(url))
        query = urllib.parse.parse_qs(parsed[4])
        if message:
            query["msg"] = [message[:200]]
        parsed[4] = urllib.parse.urlencode(query, doseq=True)
        full_url = urllib.parse.urlunparse(parsed)

        try:
            urllib.request.urlopen(full_url, timeout=10)
            self.log.debug("[Healthchecks] Ping sent to %s", suffix or "/")
            return True
        except urllib.error.URLError as exc:
            self.log.warning("[Healthchecks] Ping failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    def ping_success(self, message: str = "") -> None:
        self._hit("", message)

    def ping_failure(self, message: str = "") -> None:
        self._hit("/fail", message)

    # ------------------------------------------------------------------
    def send_test(self) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"Test ping from SolarEdge monitor at {timestamp}"
        self.ping_success(msg)
        self.ping_failure(msg)
