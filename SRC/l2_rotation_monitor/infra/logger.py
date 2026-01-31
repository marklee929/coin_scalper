import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import LOG_DIR, LOG_LEVEL

logger = logging.getLogger("l2_rotation")


def setup_logging() -> None:
    if logger.handlers:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        Path(LOG_DIR) / "l2_rotation.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

