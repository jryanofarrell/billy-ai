"""File logging for the desktop app, written under the user's app-data folder."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from parts_parser.config import app_data_dir

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_file_path() -> Path:
    logs_dir = app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "parts_parser.log"


def setup_logging(level: int = logging.INFO) -> Path:
    """Attach a rotating file handler to the package logger; safe to call twice."""

    target = log_file_path()
    root = logging.getLogger("parts_parser")
    root.setLevel(level)
    already_attached = any(
        isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == target
        for handler in root.handlers
    )
    if not already_attached:
        handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    return target
