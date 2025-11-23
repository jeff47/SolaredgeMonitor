#!/usr/bin/env python3
"""
Test harness for:
  - Config loader
  - ModbusReader
  - HealthEvaluator

This runs a single cycle of Modbus reads and prints the
resulting system health in a clear format.
"""

import sys
from pathlib import Path

from solaredge_monitor.config import Config
from solaredge_monitor.services.modbus_reader import ModbusReader
from solaredge_monitor.services.health_evaluator import HealthEvaluator
from solaredge_monitor.logging import ConsoleLog


CONFIG_PATH = "solaredge_monitor.conf"


def pretty_print_reading(r):
    if r is None:
        return "None"
    if getattr(r, "error", None):
        return f"ERROR: {r.error}"
    pac = r.pac_w or 0.0
    vdc = r.vdc_v or 0.0
    idc = r.idc_a or 0.0
    return (
        f"serial={r.serial}, "
        f"model={r.model}, "
        f"status={r.status}, "
        f"PAC={pac:.1f}W, "
        f"Vdc={vdc:.1f}V, "
        f"Idc={idc:.3f}A"
    )


def main():
    log = ConsoleLog(level="INFO", quiet=False).setup()

    # ------------------------
    # Load config
    # ------------------------
    if not Path(CONFIG_PATH).exists():
        print(f"ERROR: No config file at {CONFIG_PATH}")
        sys.exit(1)

    cfg = Config.load(CONFIG_PATH)

    # ------------------------
    # Initialize Modbus
    # ------------------------
    reader = ModbusReader(cfg.modbus, log)

    # ------------------------
    # Read all inverters
    # ------------------------
    print("=== MODBUS READINGS ===")
    try:
        readings = reader.read_all()
    except Exception as e:
        print(f"Modbus error: {e}")
        sys.exit(2)

    for name, r in readings.items():
        print(f"{name}: {pretty_print_reading(r)}")

    # ------------------------
    # Health evaluation
    # ------------------------
    evaluator = HealthEvaluator(cfg.health, log)
    system = evaluator.evaluate(readings)

    print("\n=== SYSTEM HEALTH ===")
    if system.system_ok:
        print("System OK")
    else:
        print("System NOT OK")
        print(f"Reason: {system.reason}")

    print("\n=== INVERTER STATES ===")
    for name, inv in system.per_inverter.items():
        print(f"{name}: ok={inv.inverter_ok}, reason={inv.reason}")

    # Exit code indicates success/failure
    return 0 if system.system_ok else 10


if __name__ == "__main__":
    sys.exit(main())
