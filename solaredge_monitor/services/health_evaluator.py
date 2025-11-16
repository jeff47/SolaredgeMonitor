class HealthEvaluator:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def evaluate(self, inverters, prod, optimizers, daylight):
        self.log.debug("Evaluating system health...")
        return None
