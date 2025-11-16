class AlertStateManager:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def decide(self, health):
        self.log.debug("Applying alert suppression logic...")
        return []
