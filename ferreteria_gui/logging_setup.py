import logging
from datetime import datetime

from .config import LOG_DIR


def configure_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ferreteria_gui")
    if not logger.handlers:
        handler = logging.FileHandler(LOG_DIR / f"pos_{datetime.now():%Y-%m-%d}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler); logger.setLevel(logging.INFO)
    return logger
