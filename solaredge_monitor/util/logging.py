import logging
import sys


def setup_logging(debug: bool = False, quiet: bool = False):
    """
    Configure root logger according to CLI flags.
    """
    level = logging.DEBUG if debug else logging.INFO
    if quiet:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Lightweight accessor for module-level or test harness loggers.

    Always returns a child logger that obeys the global logging setup.
    """
    return logging.getLogger(name)
