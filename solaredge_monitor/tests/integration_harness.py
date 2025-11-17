# solaredge_monitor/tests/integration_harness.py

"""Reusable integration test harness for end-to-end scenarios.

The harness wires together:
  * MockModbusReader → produces ``InverterSnapshot`` objects
  * HealthEvaluator  → per-inverter + peer health logic
  * evaluate_alerts  → end-user alert evaluation (daylight sensitive)

Tests can describe a scenario using plain dicts, optionally specify a
daylight ``phase`` (pre-dawn, mid-day, dusk, etc.), and then assert on the
resulting ``SystemHealth`` object or emitted alerts. This keeps future
daylight-aware logic testable without needing the real Modbus or notifier
stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from solaredge_monitor.config import HealthConfig
from solaredge_monitor.models.inverter import InverterSnapshot
from solaredge_monitor.models.system_health import SystemHealth
from solaredge_monitor.services.alert_logic import Alert, evaluate_alerts
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.tests.fake_reader import MockModbusReader
from solaredge_monitor.util.logging import get_logger, setup_logging


# ---------------------------------------------------------------------------
# Scenario metadata helpers
# ---------------------------------------------------------------------------

DEFAULT_PHASE_DATE = date(2024, 6, 21)  # arbitrary but fixed for reproducibility
PHASE_TIME_MAP: Dict[str, time] = {
    "pre_dawn": time(5, 0),
    "sunrise": time(6, 30),
    "morning": time(8, 0),
    "mid_day": time(12, 0),
    "afternoon": time(15, 0),
    "dusk": time(20, 30),
    "night": time(23, 0),
}


@dataclass
class IntegrationScenario:
    """Description of an end-to-end integration test."""

    name: str
    values: Dict[str, Optional[Dict[str, Any]]]
    phase: str = "mid_day"
    now: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def resolve_now(self) -> datetime:
        """Return a deterministic timestamp for the scenario."""
        if self.now is not None:
            return self.now

        phase_key = (self.phase or "mid_day").lower()
        phase_time = PHASE_TIME_MAP.get(phase_key, PHASE_TIME_MAP["mid_day"])
        return datetime.combine(DEFAULT_PHASE_DATE, phase_time)


@dataclass
class IntegrationResult:
    """Container with health + alerts produced by the harness."""

    scenario: IntegrationScenario
    now: datetime
    readings: Dict[str, Optional[InverterSnapshot]]
    health: SystemHealth
    alerts: List[Alert]


class IntegrationTestHarness:
    """High-level orchestration for Modbus → health → alert evaluation."""

    def __init__(
        self,
        health_cfg: Optional[HealthConfig] = None,
        log_name: str = "integration-test",
    ) -> None:
        setup_logging(debug=False)
        self.log = get_logger(log_name)
        self.health_cfg = health_cfg or HealthConfig(
            peer_ratio_threshold=0.60,
            min_production_for_peer_check=200,
            low_light_peer_skip_threshold=20,
        )
        self.evaluator = HealthEvaluator(self.health_cfg, self.log)

    def run(self, scenario: IntegrationScenario) -> IntegrationResult:
        """Execute a scenario and return the resulting health + alerts."""

        now = scenario.resolve_now()

        reader = MockModbusReader(scenario.values, self.log)
        snapshots = reader.read_all()

        health = self.evaluator.evaluate(snapshots)
        alerts = evaluate_alerts(health, now)

        return IntegrationResult(
            scenario=scenario,
            now=now,
            readings=snapshots,
            health=health,
            alerts=alerts,
        )


__all__ = [
    "IntegrationScenario",
    "IntegrationResult",
    "IntegrationTestHarness",
]
