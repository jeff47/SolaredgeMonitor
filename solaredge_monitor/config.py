# solaredge_monitor/config.py
from dataclasses import dataclass
from pathlib import Path
import configparser


@dataclass
class InverterConfig:
    name: str
    host: str
    port: int
    unit: int


@dataclass
class ModbusConfig:
    inverters: list[InverterConfig]
    retries: int
    timeout: float


@dataclass
class PushoverConfig:
    token: str | None
    user: str | None
    enabled: bool


@dataclass
class HealthchecksConfig:
    ping_url: str | None
    enabled: bool


@dataclass
class AlertsConfig:
    # Simple: any alert → send pushover + mark HC fail
    enabled: bool

@dataclass
class HealthConfig:
    peer_ratio_threshold: float
    min_production_for_peer_check: float
    low_light_peer_skip_threshold: float = 20.0

@dataclass
class AppConfig:
    modbus: ModbusConfig
    pushover: PushoverConfig
    healthchecks: HealthchecksConfig
    alerts: AlertsConfig
    health: HealthConfig


class Config:
    def __init__(self, path: str):
        self.path = Path(path)
        self.parser = configparser.ConfigParser()
        read = self.parser.read(self.path)
        if not read:
            raise FileNotFoundError(f"Config file not found: {self.path}")

    @classmethod
    def load(cls, path: str) -> AppConfig:
        cfg = cls(path)

        p = cfg.parser

        # --- Modbus ---
        inverters: list[InverterConfig] = []
        if "modbus" not in p:
            raise ValueError("[modbus] section missing from config")

        inv_names = p["modbus"].get("inverters", "")
        for name in [x.strip() for x in inv_names.split(",") if x.strip()]:
            sec = f"inverter:{name}"
            if sec not in p:
                raise ValueError(f"Missing section [{sec}] for inverter '{name}'")
            inv_sec = p[sec]
            inverters.append(
                InverterConfig(
                    name=name,
                    host=inv_sec["host"],
                    port=int(inv_sec.get("port", "1502")),
                    unit=int(inv_sec.get("unit", "1")),
                )
            )

        modbus = ModbusConfig(
            inverters=inverters,
            retries=int(p["modbus"].get("retries", "3")),
            timeout=float(p["modbus"].get("timeout", "3.0")),
        )

        # --- Pushover ---
        pushover_sec = p["pushover"] if "pushover" in p else {}
        pushover = PushoverConfig(
            token=pushover_sec.get("token"),
            user=pushover_sec.get("user"),
            enabled=pushover_sec.get("enabled", "false").lower() == "true",
        )

        # --- Healthchecks ---
        hc_sec = p["healthchecks"] if "healthchecks" in p else {}
        healthchecks = HealthchecksConfig(
            ping_url=hc_sec.get("ping_url"),
            enabled=hc_sec.get("enabled", "false").lower() == "true",
        )

        # --- Alerts ---
        alerts_sec = p["alerts"] if "alerts" in p else {}
        alerts = AlertsConfig(
            enabled=alerts_sec.get("enabled", "true").lower() == "true",
        )

        # --- Health ---
        health_sec = p["health"] if "health" in p else {}
        health_cfg = HealthConfig(
            peer_ratio_threshold=float(health_sec.get("peer_ratio_threshold", "0.20")),
            min_production_for_peer_check=float(health_sec.get("min_production_for_peer_check", "50")),
        )


        return AppConfig(
            modbus=modbus,
            pushover=pushover,
            healthchecks=healthchecks,
            alerts=alerts,
            health=health_cfg,
        )
