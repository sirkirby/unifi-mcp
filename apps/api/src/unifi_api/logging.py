"""Structured JSON logging to stderr.

stderr (not stdout) so it doesn't collide with anything that might write JSON-RPC
responses on stdout. Container log drivers pick it up either way.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
key_id_prefix_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("key_id_prefix", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": record.getMessage(),
        }
        payload["logger"] = record.name
        rid = request_id_ctx.get()
        if rid is not None:
            payload["request_id"] = rid
        kpfx = key_id_prefix_ctx.get()
        if kpfx is not None:
            payload["key_id_prefix"] = kpfx
        # extra= kwargs land on record.__dict__ — pull anything not in the standard set
        standard = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in standard and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    # Remove existing handlers to avoid duplication on reconfigure
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def attach_rotating_file_handler(
    *,
    path: Path,
    max_bytes: int,
    backup_count: int,
    level: str = "INFO",
) -> logging.handlers.RotatingFileHandler:
    """Attach a RotatingFileHandler to the root logger using JsonFormatter.

    Creates the parent directory if it doesn't exist. Returns the handler so
    callers can hold a reference for shutdown / testing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
    return handler
