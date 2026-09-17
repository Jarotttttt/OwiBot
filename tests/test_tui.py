"""TUI helper tests: parsing, store, local commands, pending cards. Offline."""
import pytest

from owibot.cli.tui import MessageStore, parse_local, status_line
from owibot.cli.cli import handle_local, pending_card
from owibot.agent.core import Agent


@pytest.fixture
def agent(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "USER.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")

    class FakeLLM:
        model = "fake"
        def chat(self, messages, tools=None):
            return {"text": "hi", "tool_calls": []}

    a = Agent(workspace=tmp_path, llm=FakeLLM(), chat_id="t")
    a.tools.require_approval = False
    return a


def test_parse_local():
    assert parse_local("/model x") == ("model", "x")
    assert parse_local("/new") == ("new", "")
    assert parse_local("hello there") == ("", "hello there")
    assert parse_local("/MEMORY pending") == ("memory", "pending")


def test_store_roles():
    s = MessageStore()
    s.add("user", "hi")
    s.add("bot", "yo")
    s.add("sys", "note")
    frags = s.formatted()
    assert any("hi" in t for _, t in frags)
    assert any("›" in t or "›" in t for _, t in frags)


def test_status_line():
    frags = status_line("m", 2, 5, "1/2", False)
    text = " ".join(t for _, t in frags)
    assert "m" in text and "ready" in text
    busy = " ".join(t for _, t in status_line("m", 0, 0, "x", True))
    assert "working" in busy


def test_handle_local(agent):
    assert handle_local(agent, "usage", "") is not None
    assert "Session t" in handle_local(agent, "usage", "")
    assert handle_local(agent, "frobnicate", "") is None
    assert "Usage" in handle_local(agent, "approve", "")
    assert "fake" in handle_local(agent, "model", "")


def test_pending_card_none():
    class A:
        pending = {}
    assert pending_card(A(), "plain text") is None
    assert "expired" in pending_card(A(), "⟪PENDING:p9⟫ hello")


def test_pending_card_approve(agent):
    out = agent.tools.exec("hostname")
    from owibot.agent.tools import parse_pending_marker
    agent.tools.require_approval = True
    out = agent.tools.exec("hostname")
    pid = parse_pending_marker(out)
    agent.pending[pid] = {"messages": [], "tc": {}, "steps_left": 1,
                          "op": agent.tools.pending_ops.pop(pid),
                          "top_level": True, "user_text": "u", "is_cron": False, "calls": 0}
    card = pending_card(agent, out)
    assert f"/approve {pid}" in card and f"/deny {pid}" in card


def test_build_app_headless(tmp_path):
    from owibot.cli.tui import build_app
    try:
        app = build_app(MessageStore(), lambda: status_line("m", 0, 0, "x", False),
                        str(tmp_path / "hist"))
    except Exception:
        pytest.skip("no console for prompt_toolkit app in this env")
    assert app is not None
