"""
core.logger
~~~~~~~~~~~~

Structured logging for the OpenClaw system.

Provides ``get_logger`` which returns a stdlib logger pre-configured with
JSON-friendly structured output so every decision, action, and outcome is
auditable (AI_RULES.md, Operational Rule #5).

Features
--------
* **Console handler** -- colored, human-readable format on stderr.
* **Rotating file handler** -- writes to ``logs/openclaw.log`` with automatic
  rotation at 10 MB and 5 backups.
* **Structured JSON handler** -- optional JSON-lines handler for ingestion
  by log aggregators (ELK, Loki, etc.).
* **Configurable level** -- set via ``LOG_LEVEL`` env var or settings.
* **``log_event`` helper** -- emits structured key=value log lines for
  machine-parseable audit trails.

Usage::

    from src.core.logger import get_logger, log_event

    logger = get_logger("orchestrator.controller")
    logger.info("Controller started")
    log_event(logger, "agent.dispatched", agent="research", task_id="abc123")
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.constants import (
    DEFAULT_LOG_BACKUP_COUNT,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_MAX_BYTES,
)

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_CONFIGURED = False
_ROOT_LOGGER_NAME = "openclaw"


# ---------------------------------------------------------------------------
# Custom JSON formatter
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Fields: ``timestamp``, ``level``, ``logger``, ``message``, and any
    ``extra`` data attached via the ``extra`` kwarg of the logging call.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Capture filename and line number for debugging
        if record.pathname:
            log_entry["source"] = f"{record.pathname}:{record.lineno}"

        # Include exception info when present
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Merge any extra fields that were passed explicitly
        # (stdlib attaches a lot of internal keys; filter to custom ones)
        _stdlib_keys = {
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "pathname", "filename", "module", "levelno", "levelname",
            "message", "msecs", "processName", "process", "threadName",
            "thread", "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in _stdlib_keys and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry, default=str)


# ---------------------------------------------------------------------------
# Setup function
# ---------------------------------------------------------------------------

def setup_logging(
    level: str | None = None,
    log_file: str | None = None,
    enable_json: bool = False,
    enable_console: bool = True,
    enable_file: bool = True,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
) -> logging.Logger:
    """Configure the root ``openclaw`` logger with handlers.

    This function is idempotent -- calling it multiple times replaces the
    existing handler configuration rather than duplicating handlers.

    Parameters
    ----------
    level:
        Logging level string (e.g. ``"DEBUG"``, ``"INFO"``).  Falls back
        to the ``LOG_LEVEL`` environment variable, then to
        :data:`DEFAULT_LOG_LEVEL`.
    log_file:
        Path to the rotating log file.  ``None`` uses the default from
        constants.  Parent directories are created automatically.
    enable_json:
        If ``True``, add a JSON-lines handler writing to
        ``<log_file>.json`` for structured log ingestion.
    enable_console:
        If ``True``, add a ``StreamHandler`` writing to stderr.
    enable_file:
        If ``True``, add a ``RotatingFileHandler``.
    max_bytes:
        Maximum size of a single log file before rotation.
    backup_count:
        Number of rotated backups to keep.

    Returns
    -------
    logging.Logger
        The configured root ``openclaw`` logger.
    """
    global _CONFIGURED  # noqa: PLW0603

    resolved_level = (level or os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)).upper()
    resolved_file = log_file or DEFAULT_LOG_FILE
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(numeric_level)

    # Remove existing handlers to allow re-configuration
    root.handlers.clear()

    # ── Console handler ─────────────────────────────────────────────
    if enable_console:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(numeric_level)
        console.setFormatter(
            logging.Formatter(DEFAULT_LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")
        )
        root.addHandler(console)

    # ── Rotating file handler ───────────────────────────────────────
    if enable_file:
        log_path = Path(resolved_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(
            logging.Formatter(DEFAULT_LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S")
        )
        root.addHandler(file_handler)

    # ── JSON handler (optional) ─────────────────────────────────────
    if enable_json:
        json_path = Path(resolved_file).with_suffix(".json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_handler = logging.handlers.RotatingFileHandler(
            filename=str(json_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        json_handler.setLevel(numeric_level)
        json_handler.setFormatter(JSONFormatter())
        root.addHandler(json_handler)

    _CONFIGURED = True
    return root


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------

def _configure_root() -> None:
    """One-time root logger configuration with sensible defaults."""
    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED:
        return
    setup_logging(enable_file=False, enable_json=False)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``openclaw`` namespace.

    Parameters
    ----------
    name:
        Dot-separated module path, e.g. ``"orchestrator.controller"``.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    _configure_root()
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **kwargs: Any,
) -> None:
    """Emit a structured log event with arbitrary key-value context.

    Parameters
    ----------
    logger:
        Logger instance to write to.
    event:
        Short machine-readable event name, e.g. ``"agent.started"``.
    level:
        Logging level (default INFO).
    **kwargs:
        Extra context fields attached to the message.

    Examples
    --------
    >>> log_event(logger, "pipeline.step.completed", step="seo_check", duration_ms=142)
    """
    parts = [f"event={event}"]
    for key, value in kwargs.items():
        parts.append(f"{key}={value!r}")
    logger.log(level, " | ".join(parts))
