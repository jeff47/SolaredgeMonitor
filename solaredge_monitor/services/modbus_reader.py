class ModbusReader:
    def __init__(self, cfg, log):
        self.cfg = cfg
        self.log = log

    def read_all(self):
        self.log.debug("Reading Modbus data...")
        return []
