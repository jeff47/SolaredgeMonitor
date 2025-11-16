class DaylightPolicy:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def get_info(self, now):
        self.log.debug(f"Computing daylight info at {now}...")
        return None
