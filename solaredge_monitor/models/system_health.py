from dataclasses import dataclass

@dataclass
class HealthIssue:
    severity: str   # OK, WARN, ALERT
    message: str
    inverter_serial: str | None = None

@dataclass
class SystemHealth:
    overall_status: str
    issues: list[HealthIssue]
    summary: str
