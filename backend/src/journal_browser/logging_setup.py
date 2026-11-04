"""Structured logging for the API and harvest jobs.

Three pieces, all stdlib-only:

- A request-ID context variable and filter: every log line carries the
  request that produced it (see RequestObservabilityMiddleware in main.py).
  Inbound X-Request-ID headers are honored and echoed on the response;
  anything else gets a fresh id.
- A redaction filter: password/token/secret-looking substrings never reach
  the log, in plain or JSON form.
- A JSON formatter, selected with JB_LOG_FORMAT=json, for compose log
  drivers that prefer one-line JSON. Default is human-readable text with
  the request id in brackets.

Call configure_logging() once at process start (the app factory does;
harvest entrypoints can too). Safe to call repeatedly.
"""

import json
import logging
import os
import re
import uuid
from collections.abc import Mapping
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

#: Header the middleware honors/echoes. Keep in sync with the CORS
#: expose_headers list in main.py.
REQUEST_ID_HEADER = "x-request-id"

_SECRET_KEY_RE = re.compile(
    r"(?i)((?<![\w-])(?:[a-z0-9_-]*[_-])?"
    r"(?:password|passwd|secret|token|api[_-]?key|authorization))\s*([=:])\s*\S+"
)
_SECRET_JSON_RE = re.compile(
    r'(?i)"(password|passwd|secret|token|api[_-]?key|authorization)"\s*:\s*"[^"]*"'
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._-]+")


def redact(message: str) -> str:
    """Mask credential-looking substrings: key=value pairs, JSON fields,
    and Bearer tokens."""
    message = _SECRET_KEY_RE.sub(r"\1\2***", message)
    message = _SECRET_JSON_RE.sub(r'"\1": "***"', message)
    return _BEARER_RE.sub("Bearer ***", message)


def new_request_id() -> str:
    """Short id that is unique enough to grep a request across services."""
    return uuid.uuid4().hex[:16]


class RequestContextFilter(logging.Filter):
    """Attach the current request id (or '-') to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class RedactionFilter(logging.Filter):
    """Scrub credential-looking substrings from the rendered message."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        # Redact only str args; stringifying non-str args (ints for %d, etc.)
        # breaks lazy %-formatting at emit time. A mapping stored as args
        # (logging's single-dict convention) must stay a mapping, or %-style
        # rendering breaks; only its string values are redacted. Rendered
        # messages are redacted again by formatters.
        if isinstance(record.args, Mapping):
            record.args = {
                k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()
            }
        elif record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, message, request_id."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Install the redaction + request-id filters and, when
    JB_LOG_FORMAT=json, the JSON formatter, on the app and uvicorn
    loggers. Idempotent: existing handlers are upgraded in place instead of
    duplicated."""
    fmt = os.environ.get("JB_LOG_FORMAT", "text").strip().lower()
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger_obj = logging.getLogger(logger_name)
        for filter_cls in (RequestContextFilter, RedactionFilter):
            if not any(isinstance(f, filter_cls) for f in logger_obj.filters):
                logger_obj.addFilter(filter_cls())
        for handler in logger_obj.handlers:
            if not any(isinstance(f, RequestContextFilter) for f in handler.filters):
                handler.addFilter(RequestContextFilter())
            if not any(isinstance(f, RedactionFilter) for f in handler.filters):
                handler.addFilter(RedactionFilter())
            if fmt == "json" and not isinstance(handler.formatter, JsonFormatter):
                handler.setFormatter(JsonFormatter())
    # uvicorn installs handlers on its own loggers only, so app records would
    # otherwise die at the root logger's lastResort WARNING handler (root has
    # no handlers) and app INFO lines would never emit in any mode.
    app_logger = logging.getLogger("journal_browser")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(RequestContextFilter())
        handler.addFilter(RedactionFilter())
        if fmt == "json":
            handler.setFormatter(JsonFormatter())
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
