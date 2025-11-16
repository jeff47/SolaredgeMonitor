class NotificationManager:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def send(self, actions):
        self.log.debug(f"Sending {len(actions)} notifications...")
