class DailySummaryService:
    def __init__(self, cfg, api_client, log):
        self.cfg = cfg
        self.api = api_client
        self.log = log

    def run_for_date(self, date):
        self.log.debug(f"Running daily summary for {date}")
        return None
