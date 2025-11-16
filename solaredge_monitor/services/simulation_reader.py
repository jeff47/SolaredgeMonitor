class SimulationReader:
    def __init__(self, fault_type, cfg, log):
        self.fault_type = fault_type
        self.cfg = cfg
        self.log = log

    def read_all(self):
        self.log.debug(f"Simulating fault: {self.fault_type}")
        return []
