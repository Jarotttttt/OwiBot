from __future__ import annotations

import logging
from pathlib import Path

from ..security.secret_redactor import SecretRedactor


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return SecretRedactor.redact(original)


def configure_logging(log_file: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("owibot")
    logger.setLevel(level)

    # Menghindari duplicate handlers
    if not logger.handlers:
        formatter = RedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "owibot") -> logging.Logger:
    return logging.getLogger(name)
