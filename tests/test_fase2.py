"""Fase 2 tests: approval gate, clarify, execute_code, delegate, web_search, voice. Offline."""
import io
import pytest
from pathlib import Path
from unittest.mock import patch

from owibot.agent.core import Agent
from owibot.agent.tools import parse_pending_marker
from owibot.channels.voice import build_multipart, make_transcriber, VoiceNotSupported


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "USER.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("test rules", encoding="utf-8")
    return tmp_path


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.model = "fake-model"
    def chat(self, messages, tools=None):
        if self.script:
            return self.script.pop(0)
        return {"text": "done", "tool_calls": []}


def test_execute_code(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]))
    a.tools.require_approval = False
    out = a.tools.execute_code("print(40 + 2)")
    assert "exit=0" in out and "42" in out
    assert "ERROR" in a.tools.execute_code("")


def test_exec_approval_roundtrip(ws):
    llm = FakeLLM([
        {"text": "", "tool_calls": [{"id": "t1", "name": "exec", "arguments": {"command": "hostname"}}]},
        {"text": "host checked", "tool_calls": []},
    ])
    a = Agent(workspace=ws, llm=llm, chat_id="c1")
    out = a.ask("check host")
    pid = parse_pending_marker(out)
    assert pid and "hostname" in out
    assert pid in a.pending
    final = a.approve(pid)
    assert final == "host checked"
    assert a.pending == {}
    assert a.memory.stats("c1")["turns"] == 1  # resumed turn still persisted


def test_exec_deny(ws):
    llm = FakeLLM([
        {"text": "", "tool_calls": [{"id": "t1", "name": "exec", "arguments": {"command": "hostname"}}]},
        {"text": "understood, skipping", "tool_calls": []},
    ])
    a = Agent(workspace=ws, llm=llm, chat_id="c1")
    pid = parse_pending_marker(a.ask("check host"))
    assert a.deny(pid) == "understood, skipping"


def test_exec_safe_and_cron_bypass(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]))
    assert "exit=" in a.tools.exec("python --version")
    assert "blocked" in a.tools.exec("shutdown /s")
    a.tools.require_approval = False
    assert "not found" in a.tools.exec("definitely-not-a-real-binary-xyz")
    a.tools.set_context({"is_cron": True})
    assert parse_pending_marker(a.tools.exec("hostname")) is None


def test_write_file_gating(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]))
    assert "OK" in a.tools.write_file("projects/x/a.txt", "hi")
    assert "OK" in a.tools.write_file("memory/note.md", "hi")
    marker = a.tools.write_file("random.txt", "hi")
    assert parse_pending_marker(marker) and "Approval needed" in marker


def test_clarify_roundtrip(ws):
    llm = FakeLLM([
        {"text": "", "tool_calls": [{"id": "t1", "name": "clarify",
                                     "arguments": {"question": "Which env?", "options": ["staging", "prod"]}}]},
        {"text": "deploying staging", "tool_calls": []},
    ])
    a = Agent(workspace=ws, llm=llm, chat_id="c1")
    out = a.ask("deploy it")
    pid = parse_pending_marker(out)
    assert pid and "Which env?" in out
    assert a.answer_clarify(pid, "staging") == "deploying staging"


def test_delegate_task(ws):
    llm = FakeLLM([
        {"text": "", "tool_calls": [{"id": "t1", "name": "delegate_task",
                                     "arguments": {"task": "count files", "budget": 3}}]},
        {"text": "child result: 3 files", "tool_calls": []},
        {"text": "parent done: 3 files", "tool_calls": []},
    ])
    a = Agent(workspace=ws, llm=llm, chat_id="c1")
    a.tools.require_approval = False
    assert a.ask("do it") == "parent done: 3 files"


def test_delegate_nested_blocked(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]))
    a.tools.set_context({"subagent": True})
    assert "nested" in a.tools.delegate_task("x").lower()


def test_web_search_mocked(ws):
    html = ('<a class="result__a" href="https://example.com/a">Example A</a>'
            '<a class="result__snippet" href="x">snippet one</a>')
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1): return html.encode()
    a = Agent(workspace=ws, llm=FakeLLM([]))
    with patch("owibot.agent.tools.urlopen", return_value=Resp()):
        out = a.tools.web_search("test query")
    assert "Example A" in out and "https://example.com/a" in out
    assert "ERROR" in a.tools.web_search("")


def test_voice_helpers():
    body, boundary = build_multipart(b"fake-audio", "memo.ogg", {"model": "whisper-1"})
    assert boundary.encode() in body and b"fake-audio" in body and b'name="model"' in body
    assert make_transcriber("http://127.0.0.1:11434/v1", "local") is None
    assert make_transcriber("https://api.openai.com/v1", "") is None
    fn = make_transcriber("https://api.openai.com/v1", "sk-x")
    assert callable(fn)
    import owibot.channels.voice as v
    with pytest.raises(VoiceNotSupported):
        v.transcribe_openai("https://openrouter.ai/api/v1", "sk-x", __file__)


def test_telegram_cards():
    from owibot.channels.telegram import TelegramGateway, TelegramSettings
    gw = TelegramGateway(TelegramSettings(token="x", allow_from=["1"]),
                         agent_factory=lambda cid="d": None, cron_path=Path("/tmp/nonexistent-cron.json"))

    class StubAgent:
        pending = {"p1": {"op": {"kind": "approve"}}}
    text, markup = gw._card(StubAgent(), "p1", "Approval needed: run `hostname`?")
    assert "hostname" in text
    assert {b.callback_data for row in markup.inline_keyboard for b in row} == {"ap:p1", "dn:p1"}

    class StubAgent2:
        pending = {"p2": {"op": {"kind": "clarify", "question": "Which?",
                                 "options": ["a", "b"]}}}
    text2, markup2 = gw._card(StubAgent2(), "p2", "")
    assert "Which?" in text2
    assert [b.callback_data for row in markup2.inline_keyboard for b in row] == ["cl:p2:0", "cl:p2:1"]
    text3, _ = gw._card(StubAgent(), "gone", "")
    assert "expired" in text3
