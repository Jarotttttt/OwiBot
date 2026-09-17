"""Test Advanced Agent Loop: Subagents, Self-Verification & Telemetry."""
from pathlib import Path
import pytest

from owibot.agent.core import Agent
from owibot.agent.lifecycle import StepStatus
from owibot.provider.base import LLMResponse, TokenUsage


class ScriptedLLM:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.model = "mock-advanced"

    def chat(self, messages, tools=None):
        if self.responses:
            resp = self.responses.pop(0)
            return LLMResponse(
                text=resp.get("text", ""),
                tool_calls=resp.get("tool_calls", []),
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model=self.model,
                latency_s=0.01,
            )
        return LLMResponse(text="Selesai.", model=self.model)


def test_subagent_delegation(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Parent calls delegate_task, then finishes
    llm = ScriptedLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "call_sub",
                    "name": "delegate_task",
                    "arguments": {"task": "Lakukan riset kecil", "budget": 3},
                }
            ],
        },
        # Child's response
        {"text": "Hasil riset dari subagent: topik A valid.", "tool_calls": []},
        # Parent wraps up
        {"text": "Berdasarkan subagent: topik A valid.", "tool_calls": []},
    ])

    parent = Agent(workspace=tmp_path, llm=llm, chat_id="parent_chat")
    result = parent.ask("Riset topik A")

    assert "topik A valid" in result
    assert parent.tracer.current_turn is not None
    assert "delegate_task" in parent.tracer.current_turn.tools_used


def test_subagent_recursion_blocked(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    llm = ScriptedLLM([])
    # Agent at depth 1
    child = Agent(workspace=tmp_path, llm=llm, chat_id="c:sub", depth=1)
    err = child.tools.delegate_task("coba sub-sub-agent")
    assert "dilarang" in err


def test_self_verification_nudge_on_error(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    captured_conversations = []

    class CapturingLLM:
        def __init__(self):
            self.model = "mock-eval"
            self.step = 0

        def chat(self, messages, tools=None):
            captured_conversations.append(list(messages))
            self.step += 1
            if self.step == 1:
                # Step 1: Tool call with invalid path causing error
                return LLMResponse(
                    text="",
                    tool_calls=[{
                        "id": "c1",
                        "name": "read_file",
                        "arguments": {"path": "non_existent_file.txt"},
                    }],
                    model=self.model,
                )
            # Step 2: Conclude after seeing error
            return LLMResponse(text="File tidak ada, saya mencoba alternatif.", model=self.model)

    agent = Agent(workspace=tmp_path, llm=CapturingLLM(), chat_id="eval_chat")
    reply = agent.ask("Baca file rahasia")

    # Fase RECOVER aktif: model menerima arahan pemulihan dan melanjutkan ke step alternatif
    assert "alternatif" in reply
    step2_messages = captured_conversations[1]
    has_recover_prompt = any(
        isinstance(m, dict) and "[Phase: Recover" in m.get("content", "")
        for m in step2_messages
    )
    assert has_recover_prompt is True
