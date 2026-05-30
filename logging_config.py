"""
Logging configuration: console + rotating file handlers.
"""

import logging
import logging.handlers
import sys

from paths import LOG_PATH


def setup_logging(level_console=logging.INFO, level_file=logging.DEBUG):
    """Configure root logger with console + rotating file handlers."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # Console handler — compact format
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level_console)
    ch.setFormatter(logging.Formatter(
        "[%(levelname)-7s] %(name)-14s %(message)s"))
    root.addHandler(ch)

    # Rotating file handler — timestamped (5 MB, 3 backups)
    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8", delay=True)
    fh.setLevel(level_file)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)-14s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(fh)

    logging.captureWarnings(True)

    return LOG_PATH
