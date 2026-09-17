"""TUI helper tests: parsing, store, local commands, pending cards. Offline."""
import pytest

from owibot.cli.tui import MessageStore, parse_local, status_frags, top_frags, summarize_args
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


def test_store_roles_and_tools():
    s = MessageStore()
    s.add("user", "hi")
    s.add("bot", "yo")
    s.add("sys", "note")
    s.add("tool", {"tool": "exec", "args": {"command": "ls -la"}, "preview": "a\nb", "secs": 0.2})
    text = " ".join(t for _, t in s.formatted())
    assert "hi" in text and "⏺ exec" in text and "ls -la" in text


def test_top_and_status_frags():
    top = " ".join(t for _, t in top_frags("proj", "m", 12))
    assert "owibot" in top and "ctx ~12%" in top
    st = " ".join(t for _, t in status_frags())
    assert "build/plan" in st


def test_summarize_args():
    assert summarize_args("exec", {"command": "ls"}) == "ls"
    assert summarize_args("x", "nope") == ""


def test_handle_local(agent):
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
    agent.tools.require_approval = True
    out = agent.tools.exec("hostname")
    from owibot.agent.tools import parse_pending_marker
    pid = parse_pending_marker(out)
    agent.pending[pid] = {"messages": [], "tc": {}, "steps_left": 1,
                          "op": agent.tools.pending_ops.pop(pid),
                          "top_level": True, "user_text": "u", "is_cron": False, "calls": 0}
    card = pending_card(agent, out)
    assert f"/approve {pid}" in card and f"/deny {pid}" in card


def test_trace_and_plan_mode(agent):
    calls = [{"id": "t1", "name": "list_dir", "arguments": {"path": "."}}]

    class FakeLLM2:
        model = "fake"
        def __init__(self): self.seen = []
        def chat(self, messages, tools=None):
            self.seen.append([t["function"]["name"] for t in (tools or [])])
            if len(self.seen) == 1:
                return {"text": "", "tool_calls": calls}
            return {"text": "done", "tool_calls": []}

    agent.llm = FakeLLM2()
    assert agent.ask("go") == "done"
    assert agent.last_trace and agent.last_trace[0]["tool"] == "list_dir"
    assert "secs" in agent.last_trace[0]

    agent2_llm = FakeLLM2()
    agent.llm = agent2_llm
    agent.ask("plan this", {"plan": True})
    assert "write_file" not in agent2_llm.seen[-1] and "exec" not in agent2_llm.seen[-1]
    assert "read_file" in agent2_llm.seen[-1]
    chars, pct = agent.context_usage()
    assert chars > 0 and 0 <= pct <= 99


def test_build_app_headless(tmp_path):
    from owibot.cli.tui import build_app
    try:
        app = build_app(MessageStore(), lambda: top_frags("p", "m", 1),
                        lambda: status_frags(), str(tmp_path / "hist"), title="build · m")
    except Exception:
        pytest.skip("no console for prompt_toolkit app in this env")
    assert app is not None
