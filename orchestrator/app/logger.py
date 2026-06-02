import logging
import os
from datetime import datetime

LOG_FILE = "/app/shared/volumes/pipeline.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        # File handler — persists across restarts
        fh = logging.FileHandler(LOG_FILE)
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # Console handler — shows in docker logs
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger
