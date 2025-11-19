# solaredge_monitor/config.py
from dataclasses import dataclass, field
from pathlib import Path
import configparser


@dataclass
class InverterConfig:
    name: str
    host: str
    port: int
    unit: int
    expected_optimizers: int | None = None


@dataclass
class ModbusConfig:
    inverters: list[InverterConfig]
    retries: int
    timeout: float
    skip_modbus_at_night: bool = True


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
    low_pac_threshold: float = 10.0
    low_vdc_threshold: float = 50.0


@dataclass
class DaylightConfig:
    timezone: str = "UTC"
    latitude: float | None = None
    longitude: float | None = None
    sunrise_grace_minutes: int = 30
    sunset_grace_minutes: int = 45
    summary_delay_minutes: int = 90
    static_sunrise: str | None = "06:30"
    static_sunset: str | None = "20:30"


@dataclass
class SolarEdgeAPIConfig:
    enabled: bool = False
    api_key: str | None = None
    site_id: str | None = None
    base_url: str = "https://monitoringapi.solaredge.com"
    timeout: float = 20.0
    skip_at_night: bool = False


@dataclass
class StateConfig:
    path: str | None = None


@dataclass
class AppConfig:
    modbus: ModbusConfig
    pushover: PushoverConfig
    healthchecks: HealthchecksConfig
    alerts: AlertsConfig
    health: HealthConfig
    daylight: DaylightConfig
    solaredge_api: SolarEdgeAPIConfig
    state: StateConfig


class Config:
    def __init__(self, path: str):
        self.path = Path(path)
        self.parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
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
                    expected_optimizers=(int(inv_sec["expected_optimizers"]) if "expected_optimizers" in inv_sec else None),
                )
            )

        skip_modbus = p["modbus"].get("skip_modbus_at_night", "true").lower() == "true"

        modbus = ModbusConfig(
            inverters=inverters,
            retries=int(p["modbus"].get("retries", "3")),
            timeout=float(p["modbus"].get("timeout", "3.0")),
            skip_modbus_at_night=skip_modbus,
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
            low_light_peer_skip_threshold=float(health_sec.get("low_light_peer_skip_threshold", "20.0")),
            low_pac_threshold=float(health_sec.get("low_pac_threshold", "10.0")),
            low_vdc_threshold=float(health_sec.get("low_vdc_threshold", "50.0")),
        )

        # --- Daylight ---
        daylight_sec = p["daylight"] if "daylight" in p else {}

        def _maybe_float(key: str) -> float | None:
            raw = daylight_sec.get(key)
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                return None
            return float(raw)

        daylight_cfg = DaylightConfig(
            timezone=daylight_sec.get("timezone", "UTC"),
            latitude=_maybe_float("latitude"),
            longitude=_maybe_float("longitude"),
            sunrise_grace_minutes=int(daylight_sec.get("sunrise_grace_minutes", "30")),
            sunset_grace_minutes=int(daylight_sec.get("sunset_grace_minutes", "45")),
            summary_delay_minutes=int(daylight_sec.get("summary_delay_minutes", "90")),
            static_sunrise=daylight_sec.get("static_sunrise", "06:30"),
            static_sunset=daylight_sec.get("static_sunset", "20:30"),
        )

        # --- SolarEdge API ---
        se_api_sec = p["solaredge_api"] if "solaredge_api" in p else {}

        solaredge_api_cfg = SolarEdgeAPIConfig(
            enabled=se_api_sec.get("enabled", "false").lower() == "true",
            api_key=(
                se_api_sec.get("api_key")
                or se_api_sec.get("solaredge_api_key")
            ),
            site_id=(
                se_api_sec.get("site_id")
                or se_api_sec.get("solaredge_site_id")
            ),
            base_url=se_api_sec.get("base_url", "https://monitoringapi.solaredge.com"),
            timeout=float(se_api_sec.get("timeout", "20")),
            skip_at_night=se_api_sec.get("skip_se_api_at_night", "false").lower() == "true",
        )


        # --- State ---
        state_sec = p["state"] if "state" in p else {}
        state_cfg = StateConfig(
            path=state_sec.get("path"),
        )

        return AppConfig(
            modbus=modbus,
            pushover=pushover,
            healthchecks=healthchecks,
            alerts=alerts,
            health=health_cfg,
            daylight=daylight_cfg,
            solaredge_api=solaredge_api_cfg,
            state=state_cfg,
        )
