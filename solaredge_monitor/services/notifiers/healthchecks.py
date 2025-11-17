# solaredge_monitor/services/notifiers/healthchecks.py

import urllib.request
import urllib.error
import sys
from solaredge_monitor.config import HealthchecksConfig


class HealthchecksNotifier:
    """
    Single check endpoint. For success: /ping/<id>
    For failure: /ping/<id>/fail or query string with message.
    """

    def __init__(self, cfg: HealthchecksConfig, log):
        self.cfg = cfg
        self.log = log

    def ping_success(self):
        if not self.cfg.enabled or not self.cfg.ping_url:
            return
        url = self.cfg.ping_url
        try:
            urllib.request.urlopen(url, timeout=10)
            self.log.debug("[Healthchecks] Success ping sent.")
        except Exception as e:
            print(f"⚠️ Healthchecks success ping failed: {e}", file=sys.stderr)

    def ping_failure(self, msg: str = ""):
        if not self.cfg.enabled or not self.cfg.ping_url:
            return
        # Very simple: append /fail, ignore msg for now
        url = self.cfg.ping_url.rstrip("/") + "/fail"
        try:
            urllib.request.urlopen(url, timeout=10)
            self.log.debug("[Healthchecks] Failure ping sent.")
        except Exception as e:
            print(f"⚠️ Healthchecks failure ping failed: {e}", file=sys.stderr)
