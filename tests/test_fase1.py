"""Fase 1 tests: Hermes-style memory, skills, prompt freeze, session ops. Offline."""
import json
import pytest
from pathlib import Path

from owibot.agent.memory import MemoryStore, MemoryError, MEMORY_BUDGET
from owibot.agent.skills import SkillsLoader
from owibot.agent.core import Agent


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
        assert isinstance(messages[0]["content"], str)
        if self.script:
            return self.script.pop(0)
        return {"text": "done", "tool_calls": []}


def test_memory_add_replace_remove(ws):
    m = MemoryStore(ws)
    assert "OK" in m.add("memory", "server runs debian 12")
    assert "duplicate" in m.add("memory", "server runs debian 12").lower()
    assert "OK" in m.replace("memory", "debian", "server runs debian 13")
    assert "debian 13" in m.read_memory()
    assert "OK" in m.remove("memory", "debian 13")
    assert "debian" not in m.read_memory()


def test_memory_ambiguous_and_missing(ws):
    m = MemoryStore(ws)
    m.add("memory", "project uses python 3.11")
    m.add("memory", "project uses ruff")
    with pytest.raises(MemoryError):
        m.replace("memory", "project uses", "x")
    with pytest.raises(MemoryError):
        m.remove("memory", "nonexistent-fact-xyz")


def test_memory_budget_errors_not_silent_trim(ws):
    m = MemoryStore(ws)
    with pytest.raises(MemoryError) as e:
        m.add("memory", "z" * 501)
    assert "500" in str(e.value)
    m.memory_path.write_text("§".join(f"entry-{i}-" + "x" * 100 for i in range(30)) + "\n", encoding="utf-8")
    with pytest.raises(MemoryError) as e2:
        m.add("memory", "one more fact here")
    assert "Consolidate" in str(e2.value)


def test_user_target(ws):
    m = MemoryStore(ws)
    assert "OK" in m.add("user", "prefers concise replies, timezone Asia/Jakarta")
    assert "concise" in m.snapshot()
    assert "USER PROFILE" in m.snapshot()


def test_session_search_and_stats(ws):
    m = MemoryStore(ws)
    m.append_turn("how do I deploy staging?", "use the deploy script", chat="c1")
    m.append_turn("unrelated chatter", "ok", chat="c1")
    hits = m.search_history("deploy staging", chat="c1")
    assert hits and "deploy script" in hits[0]
    st = m.stats("c1")
    assert st["turns"] == 2 and st["chars"] > 0
    m.save_meta("c1", "model", "x/y")
    assert m.load_meta("c1", "model") == "x/y"
    prompts = m.recent_prompts("c1")
    assert len(prompts) == 2


def test_skills_crud_and_view(ws):
    s = SkillsLoader(ws)
    body = "---\nname: deploy\ndescription: deploy staging workflow\n---\n\n# Deploy\n\n## When to Use\non fridays\n\n## Procedure\n1. run script\n\n## Pitfalls\n- none\n\n## Verification\ncheck url\n"
    path = s.save_skill("deploy", body)
    assert "SKILL.md" in path
    assert "deploy: deploy staging workflow" in s.index_text()
    assert "## Procedure" in s.view("deploy")
    s.patch_skill("deploy", "on fridays", "on fridays after tests pass")
    assert "after tests pass" in s.view("deploy")
    with pytest.raises(ValueError):
        s.patch_skill("deploy", "nope-nomatch", "x")
    assert s.delete_skill("deploy") is True
    assert s.delete_skill("deploy") is False


def test_prompt_freeze(ws):
    agent = Agent(workspace=ws, llm=FakeLLM([]), chat_id="c9")
    before = agent._snapshot
    agent.memory.add("memory", "brand new fact for freeze test")
    assert agent._snapshot == before  # frozen until reset
    agent.reset()
    assert agent._snapshot != before


def test_session_ops(ws):
    llm = FakeLLM([{"text": "first answer", "tool_calls": []},
                   {"text": "second answer", "tool_calls": []}])
    agent = Agent(workspace=ws, llm=llm, chat_id="c2")
    assert agent.ask("hello") == "first answer"
    assert agent.retry() == "second answer"
    assert agent.undo() == "Removed the last exchange."
    assert agent.recent == []
    assert "Current model" in agent.set_model("")
    assert "m/x" in agent.set_model("m/x")
    assert "m/x" in agent.memory.load_meta("c2", "model")
    agent.ask("q"); agent.ask("q2")
    out = agent.compress()
    assert "compressed" in out
    assert agent.recent == []
    assert "Session c2" in agent.usage()


def test_learn_tip_after_many_tools(ws):
    calls = [{"id": f"c{i}", "name": "list_dir", "arguments": {"path": "."}} for i in range(6)]
    llm = FakeLLM([{"text": "", "tool_calls": calls}, {"text": "all done", "tool_calls": []}])
    agent = Agent(workspace=ws, llm=llm, chat_id="c3")
    out = agent.ask("do complex thing")
    assert "/learn" in out


def test_learn_prompt_shape():
    p = Agent.learn_prompt("deploy-staging", "run ./deploy.sh then check url")
    assert "deploy-staging" in p and "skill_manage" in p


def test_gateway_commands_registered():
    from owibot.channels.telegram import TelegramGateway, TelegramSettings
    cmds = {c.command for c in TelegramGateway.BOT_COMMANDS}
    for c in ["start", "new", "model", "retry", "undo", "compress", "usage",
              "sessions", "memory", "skills", "learn", "stop", "help"]:
        assert c in cmds
