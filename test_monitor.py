#!/usr/bin/env python3
"""
Manual wrapper around the real monitor CLI.

This script exists as a convenience entrypoint for local operator testing, but
it deliberately delegates to the production orchestration path so its behavior
matches `python -m solaredge_monitor.main`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from solaredge_monitor.main import main as app_main


CONFIG_PATH = "solaredge_monitor.conf"


def _build_argv(argv: list[str]) -> list[str]:
    user_args = list(argv[1:])

    if not any(arg == "--config" or arg.startswith("--config=") for arg in user_args):
        if not Path(CONFIG_PATH).exists():
            print(f"ERROR: No config file at {CONFIG_PATH}")
            raise SystemExit(1)
        user_args = ["--config", CONFIG_PATH, *user_args]

    commands = {"health", "simulate", "notify-test", "maintain-db"}
    if not any(arg in commands for arg in user_args):
        user_args.append("health")

    return [argv[0], *user_args]


def main() -> int:
    old_argv = sys.argv[:]
    try:
        sys.argv = _build_argv(sys.argv)
        app_main()
        return 0
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
