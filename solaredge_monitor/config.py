# solaredge_monitor/config.py
import configparser

class Config:
    def __init__(self, parser):
        self.modbus = parser["modbus"]
        self.api = parser["api"]
        self.daylight = parser["daylight"]
        self.health = parser["health"]
        self.alerts = parser["alerts"]
        self.notify = parser["notify"]
        self.summary = parser["summary"]
        self.simulation = parser["simulation"]

    @classmethod
    def load(cls, path):
        parser = configparser.ConfigParser()
        parser.read(path)
        return cls(parser)
