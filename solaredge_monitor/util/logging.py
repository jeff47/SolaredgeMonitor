import logging

def setup_logging(debug=False, quiet=False):
    level = logging.DEBUG if debug else logging.INFO
    if quiet:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    return logging.getLogger("solaredge")
