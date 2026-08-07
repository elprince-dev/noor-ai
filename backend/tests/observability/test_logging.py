"""Tests for log_json — structured lines with auto-injected request_id (Req 1.4)."""
import json
import sys
import types

from src.observability.logging import log_json


def emitted_line(capsys) -> dict:
    """Parse the single JSON line log_json printed."""
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one log line, got {len(lines)}"
    return json.loads(lines[0])


class TestLogJson:
    def test_emits_single_json_line_with_fields(self, capsys):
        log_json("info", "trace persisted", table="noor-ai-traces", count=3)
        record = emitted_line(capsys)
        assert record["level"] == "info"
        assert record["message"] == "trace persisted"
        assert record["table"] == "noor-ai-traces"
        assert record["count"] == 3

    def test_arabic_text_not_escaped(self, capsys):
        """ensure_ascii=False keeps Arabic readable in CloudWatch."""
        log_json("info", "سؤال", query="ما حكم صلاة الوتر؟")
        raw = capsys.readouterr().out
        assert "ما حكم صلاة الوتر؟" in raw

    def test_tolerates_absent_trace_context(self, capsys):
        """No trace context module / no current context ⇒ line still emits,
        just without a request_id."""
        log_json("warning", "outside any request")
        record = emitted_line(capsys)
        assert "request_id" not in record

    def test_explicit_request_id_wins(self, capsys):
        log_json("error", "manual id", request_id="explicit-id")
        assert emitted_line(capsys)["request_id"] == "explicit-id"

    def test_injects_request_id_from_current_context(self, capsys, monkeypatch):
        """When a trace context is current, its request_id is auto-injected.

        trace_context.py ships in a later task, so a stub module stands in
        to exercise the lazy lookup path.
        """
        stub = types.ModuleType("src.observability.trace_context")

        class TraceContext:
            request_id = "ctx-request-id"

            @classmethod
            def current(cls):
                return cls

        stub.TraceContext = TraceContext
        monkeypatch.setitem(sys.modules, "src.observability.trace_context", stub)

        log_json("info", "inside a request")
        assert emitted_line(capsys)["request_id"] == "ctx-request-id"
