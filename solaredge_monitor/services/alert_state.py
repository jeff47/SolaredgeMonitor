from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from solaredge_monitor.services.alert_logic import Alert, evaluate_alerts
from solaredge_monitor.models.system_health import SystemHealth


class AlertStateManager:
    """
    Aggregates all alert sources and applies suppression/combination rules.
    Future enhancements (e.g., quiet hours, deduping) can live here while
    main.py stays thin.
    """

    def __init__(self, log):
        self.log = log

    def build_alerts(
        self,
        *,
        now: datetime,
        health: Optional[SystemHealth],
        optimizer_mismatches: Iterable[Tuple[str, int, Optional[int]]],
        extra_messages: Optional[Iterable[str]] = None,
    ) -> List[Alert]:
        alerts: list[Alert] = []

        if health:
            alerts.extend(evaluate_alerts(health, now))
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

        return alerts
