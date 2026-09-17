"""Fase 3 tests: write-approval staging + review commands. Offline."""
import pytest
from pathlib import Path

from owibot.agent.core import Agent


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "USER.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("test rules", encoding="utf-8")
    return tmp_path


class FakeLLM:
    def __init__(self, script=None):
        self.script = list(script or [])
        self.model = "fake-model"
    def chat(self, messages, tools=None):
        if self.script:
            return self.script.pop(0)
        return {"text": "done", "tool_calls": []}


def gated(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]), chat_id="c1")
    a.tools.require_approval = False
    a.tools.gate_memory_writes = True
    a.tools.gate_skill_writes = True
    return a


def test_memory_staged_not_applied(ws):
    a = gated(ws)
    out = a.tools.memory_tool("add", "memory", "gated fact here")
    assert "STAGED" in out and "/memory approve" in out
    assert "gated fact" not in a.memory.read_memory()
    assert "staged" in a.memory_review("pending").lower()
    res = a.memory_review("approve 1")
    assert "OK" in res
    assert "gated fact" in a.memory.read_memory()
    assert "No staged" in a.memory_review("pending")


def test_memory_reject(ws):
    a = gated(ws)
    a.tools.memory_tool("add", "memory", "bad fact xyz")
    assert "Rejected" in a.memory_review("reject 1")
    assert "bad fact" not in a.memory.read_memory()
    assert "No staged entry 99" in a.memory_review("approve 99")


def test_memory_gate_off_by_default(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]), chat_id="c1")
    assert "OK" in a.tools.memory_tool("add", "memory", "direct fact")


def test_skill_staged_approve_diff(ws):
    a = gated(ws)
    body = "---\nname: t\n description: x\n---\n\n# T\n\n## When to Use\nx\n\n## Procedure\n1. y\n\n## Pitfalls\n- z\n\n## Verification\nw\n"
    out = a.tools.skill_manage("create", "t-skill", body)
    assert "STAGED" in out
    assert a.skills.load_skill("t-skill") is None
    assert "staged" in a.skills_review("").lower()
    diff = a.skills_review("diff 1")
    assert "t-skill" in diff
    assert "OK" in a.skills_review("approve 1")
    assert a.skills.load_skill("t-skill") is not None
    assert "OK" in a.skills_review("reject all") or "Rejected 0" in a.skills_review("reject all")


def test_skill_patch_staged(ws):
    a = Agent(workspace=ws, llm=FakeLLM([]), chat_id="c1")
    a.tools.skill_manage("create", "ps", "---\nname: ps\ndescription: d\n---\n\nbody one two three")
    a.tools.gate_skill_writes = True
    out = a.tools.skill_manage("patch", "ps", "", "one", "ONE")
    assert "STAGED" in out
    assert "body one two" in a.skills.view("ps")  # unchanged until approved
    a.skills_review("approve all")
    assert "ONE" in a.skills.view("ps")


def test_cron_bypasses_gate(ws):
    a = gated(ws)
    a.tools.set_context({"is_cron": True})
    assert "OK" in a.tools.memory_tool("add", "memory", "cron fact")
    assert "cron fact" in a.memory.read_memory()
