from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from solaredge_monitor.services.app_state import AppState
from solaredge_monitor.services.alert_logic import Alert, evaluate_alerts
from solaredge_monitor.models.system_health import SystemHealth


class AlertStateManager:
    """
    Aggregates all alert sources and applies suppression/combination rules.
    Future enhancements (e.g., quiet hours, deduping) can live here while
    main.py stays thin.
    """

    def __init__(
        self,
        log,
        *,
        state: AppState | None = None,
        consecutive_required: int = 1,
    ):
        self.log = log
        self.state = state
        self.consecutive_required = max(1, int(consecutive_required))

    def _load_counters(self) -> dict[str, int]:
        if not self.state:
            return {}
        raw = self.state.get("health_alert_counters", {}) or {}
        counters: dict[str, int] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                try:
                    counters[key] = int(value)
                except (TypeError, ValueError):
                    continue
        return counters

    def _save_counters(self, counters: dict[str, int]) -> None:
        if self.state is None:
            return
        self.state.set("health_alert_counters", counters)

    def _update_counters(self, counters: dict[str, int], health: SystemHealth) -> bool:
        changed = False
        for name, inv_state in health.per_inverter.items():
            key = name
            if inv_state.inverter_ok:
                if counters.get(key, 0) != 0:
                    counters[key] = 0
                    changed = True
                continue
            prev = counters.get(key, 0)
            counters[key] = prev + 1
            if counters[key] != prev:
                changed = True
        return changed

    def _filter_by_consecutive(
        self,
        counters: dict[str, int],
        alerts: List[Alert],
    ) -> List[Alert]:
        if self.consecutive_required <= 1:
            return alerts

        gated: list[Alert] = []
        for alert in alerts:
            if alert.inverter_name == "SYSTEM":
                gated.append(alert)
                continue
            count = counters.get(alert.inverter_name, 0)
            if count >= self.consecutive_required:
                gated.append(alert)
        return gated

    def build_alerts(
        self,
        *,
        now: datetime,
        health: Optional[SystemHealth],
        optimizer_mismatches: Iterable[Tuple[str, int, Optional[int]]],
        extra_messages: Optional[Iterable[str]] = None,
    ) -> List[Alert]:
        alerts: list[Alert] = []

        counters = self._load_counters()
        counters_changed = False

        if health:
            counters_changed = self._update_counters(counters, health) or counters_changed
            health_alerts = evaluate_alerts(health, now)
            alerts.extend(self._filter_by_consecutive(counters, health_alerts))
        else:
            for name, expected, actual in optimizer_mismatches:
                actual_txt = "unknown" if actual is None else str(actual)
                alerts.append(
                    Alert(
                        inverter_name=name,
                        serial="CLOUD",
                        message=f"Optimizer count mismatch (expected {expected}, cloud={actual_txt})",
                        status=-1,
                        pac_w=None,
                    )
                )

        for msg in extra_messages or []:
            alerts.append(
                Alert(
                    inverter_name="SYSTEM",
                    serial="SYSTEM",
                    message=msg,
                    status=-1,
                    pac_w=None,
                )
            )

        if counters_changed:
            self._save_counters(counters)

        return alerts
