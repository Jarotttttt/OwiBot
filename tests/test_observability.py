"""Test Observability: AgentTracer, TurnTelemetry, RedactingFormatter."""
import logging
import time
from pathlib import Path

from owibot.observability import (
    AgentTracer,
    RedactingFormatter,
    configure_logging,
    get_logger,
)
from owibot.provider.base import TokenUsage


def test_tracer_records_events():
    tracer = AgentTracer(chat_id="test_chat_123")
    telemetry = tracer.start_turn(prompt="Hitung 1 + 1")

    assert telemetry.chat_id == "test_chat_123"
    assert "Hitung 1 + 1" in telemetry.prompt

    tracer.record_llm_call(
        model="gpt-test",
        usage=TokenUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
        latency_s=0.15,
    )
    tracer.record_tool_call(
        tool_name="read_file",
        args={"path": "test.txt"},
        duration_s=0.02,
        status="OK",
    )

    final = tracer.finish_turn(final_response="Hasilnya adalah 2.")
    assert final.status == "success"
    assert final.llm_calls == 1
    assert final.tokens.total_tokens == 20
    assert "read_file" in final.tools_used
    assert final.total_duration_s >= 0.0

    summary = final.to_dict()
    assert summary["status"] == "success"
    assert summary["events_count"] >= 3


def test_tracer_records_error():
    tracer = AgentTracer(chat_id="error_chat")
    tracer.start_turn(prompt="Run failure")
    final = tracer.finish_turn(final_response="", error="Connection timeout")
    assert final.status == "error"
    assert final.error_message == "Connection timeout"


def test_redacting_formatter():
    formatter = RedactingFormatter(fmt="%(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Login with sk-1234567890abcdef1234567890abcdef and 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "sk-1234567890abcdef" not in output
    assert "[REDACTED_API_KEY]" in output
    assert "[REDACTED_TELEGRAM_TOKEN]" in output
