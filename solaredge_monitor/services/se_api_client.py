class SolarEdgeAPIClient:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def get_daily_production(self, date):
        self.log.debug("Fetching daily SolarEdge production...")
        return None

    def get_optimizer_statuses(self):
        self.log.debug("Fetching optimizer statuses...")
        return None
