"""Trace emission to CloudWatch Logs (Req 3.1).

`TraceSink` keeps emission swappable — tests use an in-memory recording
sink. The production `CloudWatchTraceSink` is a plain stdout writer:
Lambda routes stdout to CloudWatch Logs, so one print() per trace yields
one structured log entry queryable by Logs Insights via `log_type`.
"""
import json
from typing import Protocol

from src.observability.models import Trace


class TraceSink(Protocol):
    """Emits one assembled Trace to its destination."""

    def emit(self, trace: Trace) -> None: ...


class CloudWatchTraceSink:
    """Emit each trace as a single JSON log line on stdout.

    The line is the trace's schema-version-1 shape plus `log_type: "trace"`
    so metric filters and Logs Insights can select trace entries.
    `ensure_ascii=False` keeps Arabic text readable in CloudWatch (Req 3.1).
    """

    def emit(self, trace: Trace) -> None:
        print(json.dumps({"log_type": "trace", **trace.to_dict()}, ensure_ascii=False))
