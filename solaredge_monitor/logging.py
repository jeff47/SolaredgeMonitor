from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable


def _default_logger_name() -> logging.Logger:
    return logging.getLogger("solaredge")

_LOG_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"


class ConsoleLog:
    """Configure console logging for the application."""

    def __init__(
        self,
        level: str = "INFO",
        quiet: bool = False,
        debug_modules: Iterable[str] | None = None,
        log_path: str | None = None,
        log_max_bytes: int = 10 * 1024 * 1024,
        log_backup_count: int = 5,
    ):
        self.level = level.upper()
        self.quiet = quiet
        self.debug_modules = list(debug_modules or [])
        self.log_path = log_path
        self.log_max_bytes = log_max_bytes
        self.log_backup_count = log_backup_count

    def setup(self) -> logging.Logger:
        # Root logger handles all levels; handlers control visibility.
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.DEBUG)

        fmt = logging.Formatter(_LOG_FMT, datefmt=_LOG_DATE_FMT)

        if not self.quiet:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(getattr(logging, self.level, logging.INFO))
            handler.setFormatter(fmt)
            root.addHandler(handler)

        if self.log_path:
            path = Path(self.log_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=self.log_max_bytes,
                backupCount=self.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(getattr(logging, self.level, logging.INFO))
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)

        for name in self.debug_modules:
            logging.getLogger(name).setLevel(logging.DEBUG)

        return _default_logger_name()


@dataclass
class RunLogEntry:
    timestamp: str
    daylight_phase: str | None
    daylight_context: dict[str, Any] | None
    inverter_snapshots: dict[str, Any] | None
    weather_snapshot: dict[str, Any] | None
    weather_expectations: dict[str, Any] | None
    residuals: dict[str, Any] | None
    health: dict[str, Any] | None
    alerts: list[dict[str, Any]] | None
    cloud_inventory: list[dict[str, Any]] | None
    optimizer_counts: dict[str, Any] | None


def _to_jsonable(obj: Any) -> Any:
    """Best-effort conversion to JSON-safe structures."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    if is_dataclass(obj):
        return _to_jsonable(asdict(obj))
    if hasattr(obj, "as_dict") and callable(getattr(obj, "as_dict")):
        try:
            return _to_jsonable(obj.as_dict())
        except Exception:
            pass
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(x) for x in obj]
    if hasattr(obj, "__dict__"):
        return _to_jsonable(vars(obj))
    return str(obj)


class StructuredLog:
    """Structured, machine-readable logging (JSONL today; extensible later)."""

    def __init__(self, path: str | None, enabled: bool = False):
        self.enabled = enabled and bool(path)
        self.path = Path(path).expanduser() if path else None
        if self.enabled and self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: RunLogEntry) -> None:
        if not self.enabled or not self.path:
            return
        payload = _to_jsonable(asdict(entry))
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, default=str) + "\n")
        except Exception as exc:  # pragma: no cover - best-effort logging
            logging.getLogger(__name__).debug("Structured log write skipped: %s", exc)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
