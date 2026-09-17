"""Test Agent Lifecycle Engine: Understand, Plan, Execute, Verify, Recover, Finalize."""
from pathlib import Path
import pytest

from owibot.agent.core import Agent
from owibot.agent.lifecycle import AgentPhase
from owibot.provider.base import LLMResponse, TokenUsage


class LifecycleScriptedLLM:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.model = "mock-lifecycle"
        self.recorded_prompts: list[list[dict]] = []

    def chat(self, messages, tools=None):
        self.recorded_prompts.append([dict(m) for m in messages])
        if self.responses:
            resp = self.responses.pop(0)
            return LLMResponse(
                text=resp.get("text", ""),
                tool_calls=resp.get("tool_calls", []),
                usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                model=self.model,
                latency_s=0.02,
            )
        return LLMResponse(text="Semua fase selesai.", model=self.model)


def test_lifecycle_complete_happy_path(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("- Catatan sistem", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Aturan dasar", encoding="utf-8")

    llm = LifecycleScriptedLLM([
        # Turn 1: execute read_file
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "read_file",
                    "arguments": {"path": "memory/MEMORY.md"},
                }
            ],
        },
        # Turn 2: conclude
        {"text": "Isi memori adalah: Catatan sistem", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="lifecycle_chat")
    phase_events: list[str] = []

    def track_progress(msg: str):
        phase_events.append(msg)

    result = agent.ask("Baca catatan memori", context={"on_progress": track_progress})

    assert "Catatan sistem" in result
    assert any("menganalisis" in e.lower() for e in phase_events)
    assert any("membaca file" in e.lower() for e in phase_events)
    assert any("menyusun jawaban" in e.lower() for e in phase_events)

    # Verifikasi rekaman tracer pada fase FINALIZE
    assert agent.tracer.current_turn is not None
    assert agent.tracer.current_turn.status == "success"
    assert agent.tracer.current_turn.llm_calls == 2
    assert "read_file" in agent.tracer.current_turn.tools_used


def test_lifecycle_plan_phase_for_complex_tasks(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Aturan dasar", encoding="utf-8")

    llm = LifecycleScriptedLLM([
        {"text": "Rencana selesai dibuat.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="plan_chat")
    # Kata 'buatkan dan implementasi' memicu fase Plan
    agent.ask("Buatkan dan implementasi script scraping data")

    assert len(llm.recorded_prompts) == 1
    system_messages = [
        m.get("content", "")
        for m in llm.recorded_prompts[0]
        if m.get("role") == "system"
    ]
    assert any("[Phase: Plan]" in msg for msg in system_messages)


def test_lifecycle_recovery_loop_on_tool_failure(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Aturan dasar", encoding="utf-8")

    llm = LifecycleScriptedLLM([
        # Step 1: Tool call gagal
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c_fail",
                    "name": "read_file",
                    "arguments": {"path": "file_hilang.txt"},
                }
            ],
        },
        # Step 2: Coba tool lain setelah menerima feedback recovery
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c_ok",
                    "name": "list_dir",
                    "arguments": {"path": "."},
                }
            ],
        },
        # Step 3: Conclude
        {"text": "Recovery berhasil melalui list_dir.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="recover_chat")
    progress_notes: list[str] = []

    res = agent.ask("Periksa file hilang", context={"on_progress": lambda m: progress_notes.append(m)})
    assert "Recovery berhasil" in res

    # Verifikasi fase RECOVER disuntikkan ke prompt step 2
    step2_prompt = llm.recorded_prompts[1]
    assert any("[Phase: Recover" in m.get("content", "") for m in step2_prompt)
    assert any("pemulihan" in note.lower() for note in progress_notes)
