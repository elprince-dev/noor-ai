"""Structured JSON log lines with auto-injected request_id (Req 1.4).

`log_json` prints exactly one JSON line per call — Lambda routes stdout to
CloudWatch Logs, so structured fields are queryable by Logs Insights.
The current request's Request_ID is injected automatically when a
TraceContext is active, so callers never thread it through by hand.
"""
import json


def _current_request_id() -> str | None:
    """Look up the active request's ID, tolerating absence.

    Lazily imports trace_context so this module has no hard dependency on
    it (and works before it exists). Returns None when no context is
    current — e.g. outside a request or with tracing not yet set up.
    """
    try:
        from src.observability.trace_context import TraceContext
    except ImportError:
        return None
    ctx = TraceContext.current()
    return ctx.request_id if ctx is not None else None


def log_json(level: str, message: str, **fields) -> None:
    """Emit one structured JSON log line.

    Args:
        level: Log level label, e.g. "info", "warning", "error".
        message: Human-readable message.
        **fields: Extra structured fields merged into the line. An explicit
            `request_id` field wins over the auto-injected one.
    """
    record: dict = {"level": level, "message": message}
    if "request_id" not in fields:
        request_id = _current_request_id()
        if request_id is not None:
            record["request_id"] = request_id
    record.update(fields)
    print(json.dumps(record, ensure_ascii=False, default=str))
