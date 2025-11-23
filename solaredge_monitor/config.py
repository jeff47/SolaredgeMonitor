# solaredge_monitor/config.py
from dataclasses import dataclass, field
from pathlib import Path
import configparser


@dataclass
class InverterConfig:
    name: str
    host: str
    port: int = 1502
    unit: int = 1
    expected_optimizers: int | None = None
    array_kw_dc: float | None = None
    ac_capacity_kw: float | None = None
    tilt_deg: float | None = None
    azimuth_deg: float | None = None


@dataclass
class ModbusConfig:
    inverters: list[InverterConfig]
    retries: int = 3
    timeout: float = 3.0
    skip_modbus_at_night: bool = True


@dataclass
class PushoverConfig:
    token: str | None = None
    user: str | None = None
    enabled: bool = False


@dataclass
class HealthchecksConfig:
    ping_url: str | None = None
    enabled: bool = False


@dataclass
class HealthConfig:
    peer_ratio_threshold: float = 0.20
    min_production_for_peer_check: float = 50.0
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
class SimulationConfig:
    scenario: str | None = None
    simulated_time: str | None = None
    settings: dict[str, str] = field(default_factory=dict)
    scenarios: dict[str, dict[str, str]] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, dict[str, str] | str]:
        root: dict[str, dict[str, str] | str] = dict(self.settings)
        for name, values in self.scenarios.items():
            root[name] = dict(values)
        return root


@dataclass
class RetentionConfig:
    snapshot_days: int = 30
    summary_days: int = 90
    vacuum_after_prune: bool = True


@dataclass
class WeatherConfig:
    enabled: bool = False
    provider: str = "open-meteo"
    latitude: float | None = None
    longitude: float | None = None
    tilt_deg: float = 20.0
    azimuth_deg: float = 180.0
    albedo: float = 0.2
    array_kw_dc: float | None = None
    ac_capacity_kw: float | None = None
    dc_ac_derate: float = 0.9
    noct_c: float = 45.0
    temp_coeff_per_c: float = -0.0045
    log_path: str | None = None


@dataclass
class LoggingConfig:
    console_level: str = "INFO"
    console_quiet: bool = False
    debug_modules: list[str] = field(default_factory=list)
    structured_enabled: bool = False
    structured_path: str | None = None


@dataclass
class AppConfig:
    modbus: ModbusConfig
    pushover: PushoverConfig
    healthchecks: HealthchecksConfig
    health: HealthConfig
    daylight: DaylightConfig
    solaredge_api: SolarEdgeAPIConfig
    state: StateConfig
    simulation: SimulationConfig
    retention: RetentionConfig
    weather: WeatherConfig
    logging: LoggingConfig


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

        def _as_bool(value: str) -> bool:
            return value.strip().lower() == "true"

        def _maybe_float(raw: str | None) -> float | None:
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                return None
            return float(raw)

        # --- Modbus ---
        inverters: list[InverterConfig] = []
        if "modbus" not in p:
            raise ValueError("[modbus] section missing from config")

        modbus_sec = p["modbus"]
        inv_names = modbus_sec.get("inverters", "")
        for name in [x.strip() for x in inv_names.split(",") if x.strip()]:
            sec = f"inverter:{name}"
            if sec not in p:
                raise ValueError(f"Missing section [{sec}] for inverter '{name}'")
            inv_sec = p[sec]
            inv_kwargs = {
                "name": name,
                "host": inv_sec["host"],
            }
            if "port" in inv_sec:
                inv_kwargs["port"] = int(inv_sec["port"])
            if "unit" in inv_sec:
                inv_kwargs["unit"] = int(inv_sec["unit"])
            if "expected_optimizers" in inv_sec:
                inv_kwargs["expected_optimizers"] = int(inv_sec["expected_optimizers"])
            if "array_kw_dc" in inv_sec:
                inv_kwargs["array_kw_dc"] = float(inv_sec["array_kw_dc"])
            if "ac_capacity_kw" in inv_sec:
                inv_kwargs["ac_capacity_kw"] = float(inv_sec["ac_capacity_kw"])
            if "tilt_deg" in inv_sec:
                inv_kwargs["tilt_deg"] = float(inv_sec["tilt_deg"])
            if "azimuth_deg" in inv_sec:
                inv_kwargs["azimuth_deg"] = float(inv_sec["azimuth_deg"])
            inverters.append(InverterConfig(**inv_kwargs))

        modbus_kwargs = {}
        if "retries" in modbus_sec:
            modbus_kwargs["retries"] = int(modbus_sec["retries"])
        if "timeout" in modbus_sec:
            modbus_kwargs["timeout"] = float(modbus_sec["timeout"])
        if "skip_modbus_at_night" in modbus_sec:
            modbus_kwargs["skip_modbus_at_night"] = _as_bool(modbus_sec["skip_modbus_at_night"])

        modbus = ModbusConfig(
            inverters=inverters,
            **modbus_kwargs,
        )

        # --- Pushover ---
        pushover_kwargs = {}
        if "pushover" in p:
            pushover_sec = p["pushover"]
            if "token" in pushover_sec:
                pushover_kwargs["token"] = pushover_sec["token"]
            if "user" in pushover_sec:
                pushover_kwargs["user"] = pushover_sec["user"]
            if "enabled" in pushover_sec:
                pushover_kwargs["enabled"] = _as_bool(pushover_sec["enabled"])
        pushover = PushoverConfig(**pushover_kwargs)

        # --- Healthchecks ---
        healthchecks_kwargs = {}
        if "healthchecks" in p:
            hc_sec = p["healthchecks"]
            if "ping_url" in hc_sec:
                healthchecks_kwargs["ping_url"] = hc_sec["ping_url"]
            if "enabled" in hc_sec:
                healthchecks_kwargs["enabled"] = _as_bool(hc_sec["enabled"])
        healthchecks = HealthchecksConfig(**healthchecks_kwargs)

        # --- Health ---
        health_kwargs = {}
        if "health" in p:
            health_sec = p["health"]
            if "peer_ratio_threshold" in health_sec:
                health_kwargs["peer_ratio_threshold"] = float(health_sec["peer_ratio_threshold"])
            if "min_production_for_peer_check" in health_sec:
                health_kwargs["min_production_for_peer_check"] = float(health_sec["min_production_for_peer_check"])
            if "low_light_peer_skip_threshold" in health_sec:
                health_kwargs["low_light_peer_skip_threshold"] = float(health_sec["low_light_peer_skip_threshold"])
            if "low_pac_threshold" in health_sec:
                health_kwargs["low_pac_threshold"] = float(health_sec["low_pac_threshold"])
            if "low_vdc_threshold" in health_sec:
                health_kwargs["low_vdc_threshold"] = float(health_sec["low_vdc_threshold"])
        health_cfg = HealthConfig(**health_kwargs)

        # --- Daylight ---
        daylight_kwargs = {}
        if "daylight" in p:
            daylight_sec = p["daylight"]
            if "timezone" in daylight_sec:
                daylight_kwargs["timezone"] = daylight_sec["timezone"]
            if (latitude := _maybe_float(daylight_sec.get("latitude"))) is not None:
                daylight_kwargs["latitude"] = latitude
            if (longitude := _maybe_float(daylight_sec.get("longitude"))) is not None:
                daylight_kwargs["longitude"] = longitude
            if "sunrise_grace_minutes" in daylight_sec:
                daylight_kwargs["sunrise_grace_minutes"] = int(daylight_sec["sunrise_grace_minutes"])
            if "sunset_grace_minutes" in daylight_sec:
                daylight_kwargs["sunset_grace_minutes"] = int(daylight_sec["sunset_grace_minutes"])
            if "summary_delay_minutes" in daylight_sec:
                daylight_kwargs["summary_delay_minutes"] = int(daylight_sec["summary_delay_minutes"])
            if "static_sunrise" in daylight_sec:
                daylight_kwargs["static_sunrise"] = daylight_sec["static_sunrise"]
            if "static_sunset" in daylight_sec:
                daylight_kwargs["static_sunset"] = daylight_sec["static_sunset"]
        daylight_cfg = DaylightConfig(**daylight_kwargs)

        # --- SolarEdge API ---
        solaredge_api_kwargs = {}
        if "solaredge_api" in p:
            se_api_sec = p["solaredge_api"]
            if "enabled" in se_api_sec:
                solaredge_api_kwargs["enabled"] = _as_bool(se_api_sec["enabled"])
            api_key = se_api_sec.get("api_key") or se_api_sec.get("solaredge_api_key")
            if api_key is not None:
                solaredge_api_kwargs["api_key"] = api_key
            site_id = se_api_sec.get("site_id") or se_api_sec.get("solaredge_site_id")
            if site_id is not None:
                solaredge_api_kwargs["site_id"] = site_id
            if "base_url" in se_api_sec:
                solaredge_api_kwargs["base_url"] = se_api_sec["base_url"]
            if "timeout" in se_api_sec:
                solaredge_api_kwargs["timeout"] = float(se_api_sec["timeout"])
            if "skip_se_api_at_night" in se_api_sec:
                solaredge_api_kwargs["skip_at_night"] = _as_bool(se_api_sec["skip_se_api_at_night"])
        solaredge_api_cfg = SolarEdgeAPIConfig(**solaredge_api_kwargs)


        # --- State ---
        state_kwargs = {}
        if "state" in p and "path" in p["state"]:
            state_kwargs["path"] = p["state"]["path"]
        state_cfg = StateConfig(**state_kwargs)

        # --- Simulation ---
        sim_scenario: str | None = None
        sim_settings: dict[str, str] = {}
        sim_time: str | None = None
        if "simulation" in p:
            sim_sec = p["simulation"]
            if "scenario" in sim_sec:
                sim_scenario_raw = sim_sec["scenario"].strip()
                sim_scenario = sim_scenario_raw or None
            if "simulated_time" in sim_sec:
                sim_time_raw = sim_sec["simulated_time"].strip()
                sim_time = sim_time_raw or None
            for key, value in sim_sec.items():
                if key in {"scenario", "simulated_time"}:
                    continue
                sim_settings[key] = value

        sim_scenarios: dict[str, dict[str, str]] = {}
        for section in p.sections():
            if not section.startswith("simulation:"):
                continue
            scenario_name = section.split(":", 1)[1].strip()
            if not scenario_name:
                continue
            sim_scenarios[scenario_name] = dict(p[section])

        simulation_cfg = SimulationConfig(
            scenario=sim_scenario,
            simulated_time=sim_time,
            settings=sim_settings,
            scenarios=sim_scenarios,
        )

        if "retention" in p:
            retention_sec = p["retention"]
        else:
            retention_sec = {}

        retention_cfg = RetentionConfig(
            snapshot_days=int(retention_sec.get("snapshot_days", 30) or 30),
            summary_days=int(retention_sec.get("summary_days", 90) or 90),
            vacuum_after_prune=(retention_sec.get("vacuum_after_prune", "true").strip().lower() == "true")
            if retention_sec
            else True,
        )

        # --- Weather ---
        weather_kwargs = {}
        if "weather" in p:
            weather_sec = p["weather"]
            if "enabled" in weather_sec:
                weather_kwargs["enabled"] = _as_bool(weather_sec["enabled"])
            if "provider" in weather_sec:
                weather_kwargs["provider"] = weather_sec["provider"]
            if "latitude" in weather_sec:
                weather_kwargs["latitude"] = float(weather_sec["latitude"])
            if "longitude" in weather_sec:
                weather_kwargs["longitude"] = float(weather_sec["longitude"])
            if "tilt_deg" in weather_sec:
                weather_kwargs["tilt_deg"] = float(weather_sec["tilt_deg"])
            if "azimuth_deg" in weather_sec:
                weather_kwargs["azimuth_deg"] = float(weather_sec["azimuth_deg"])
            if "albedo" in weather_sec:
                weather_kwargs["albedo"] = float(weather_sec["albedo"])
            if "array_kw_dc" in weather_sec:
                weather_kwargs["array_kw_dc"] = float(weather_sec["array_kw_dc"])
            if "ac_capacity_kw" in weather_sec:
                weather_kwargs["ac_capacity_kw"] = float(weather_sec["ac_capacity_kw"])
            if "dc_ac_derate" in weather_sec:
                weather_kwargs["dc_ac_derate"] = float(weather_sec["dc_ac_derate"])
            if "noct_c" in weather_sec:
                weather_kwargs["noct_c"] = float(weather_sec["noct_c"])
            if "temp_coeff_per_c" in weather_sec:
                weather_kwargs["temp_coeff_per_c"] = float(weather_sec["temp_coeff_per_c"])
            if "log_path" in weather_sec:
                weather_kwargs["log_path"] = weather_sec["log_path"]
        weather_cfg = WeatherConfig(**weather_kwargs)

        logging_kwargs = {}
        if "logging" in p:
            logging_sec = p["logging"]
            if "console_level" in logging_sec:
                logging_kwargs["console_level"] = logging_sec["console_level"]
            if "console_quiet" in logging_sec:
                logging_kwargs["console_quiet"] = _as_bool(logging_sec["console_quiet"])
            if "debug_modules" in logging_sec:
                raw = logging_sec["debug_modules"]
                logging_kwargs["debug_modules"] = [x.strip() for x in raw.split(",") if x.strip()]
            if "structured_enabled" in logging_sec:
                logging_kwargs["structured_enabled"] = _as_bool(logging_sec["structured_enabled"])
            if "structured_path" in logging_sec:
                logging_kwargs["structured_path"] = logging_sec["structured_path"]
        logging_cfg = LoggingConfig(**logging_kwargs)

        return AppConfig(
            modbus=modbus,
            pushover=pushover,
            healthchecks=healthchecks,
            health=health_cfg,
            daylight=daylight_cfg,
            solaredge_api=solaredge_api_cfg,
            state=state_cfg,
            simulation=simulation_cfg,
            retention=retention_cfg,
            weather=weather_cfg,
            logging=logging_cfg,
        )
