"""Regression test suite for bugs discovered during the comprehensive lifecycle audit."""
import tempfile
from pathlib import Path
import pytest

from owibot.agent.core import Agent
from owibot.agent.lifecycle import StepStatus, VerificationStatus
from owibot.agent.verifier import StepVerificationManager
from owibot.provider.base import LLMResponse


@pytest.fixture
def clean_workspace(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")
    return tmp_path


class InfiniteToolLLM:
    """Mock LLM yang memanggil tool terus menerus tanpa henti."""
    def __init__(self):
        self.model = "mock-infinite"

    def chat(self, messages, tools=None):
        return LLMResponse(
            text="",
            tool_calls=[{"id": "call_loop", "name": "list_dir", "arguments": {"path": "."}}],
            model=self.model,
        )


def test_bug_unexecuted_steps_should_not_be_marked_completed_on_timeout(clean_workspace):
    agent = Agent(workspace=clean_workspace, llm=InfiniteToolLLM())
    agent.max_steps = 1
    # Tugas dengan 2 langkah jelas, batas eksekusi 1 langkah
    agent.ask("1. Langkah pertama yang lama\n2. Langkah kedua yang belum pernah dijalankan")

    assert len(agent.last_plan) == 2
    step_1 = agent.last_plan[0]
    step_2 = agent.last_plan[1]

    # Langkah 2 tidak boleh berstatus COMPLETED atau PASSED karena tidak pernah dieksekusi
    assert step_2.status != StepStatus.COMPLETED
    assert step_2.verification_status != VerificationStatus.PASSED
    assert step_2.status == StepStatus.FAILED
    assert step_2.verification_status == VerificationStatus.FAILED
    assert "timeout" in step_2.verification_reason.lower()


class BatchToolsLLM:
    """Mock LLM yang mengeksekusi dua tool berbeda dalam satu turn."""
    def __init__(self):
        self.model = "mock-batch"
        self.turn = 0

    def chat(self, messages, tools=None):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                text="",
                tool_calls=[
                    {"id": "c1", "name": "write_file", "arguments": {"path": "file1.txt", "content": "konten 1"}},
                    {"id": "c2", "name": "write_file", "arguments": {"path": "file2.txt", "content": "konten 2"}},
                ],
                model=self.model,
            )
        return LLMResponse(text="Selesai semua.", model=self.model)


def test_bug_batch_tool_calls_should_verify_respective_steps(clean_workspace):
    agent = Agent(workspace=clean_workspace, llm=BatchToolsLLM())
    agent.ask("1. Buat file1.txt\n2. Buat file2.txt")

    assert len(agent.last_plan) == 2
    step_1 = agent.last_plan[0]
    step_2 = agent.last_plan[1]

    # Keduanya harus diverifikasi terhadap target masing-masing
    assert "file1.txt" in step_1.verification_evidence
    assert "file2.txt" in step_2.verification_evidence
    assert step_1.status == StepStatus.COMPLETED
    assert step_2.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED
    assert step_2.verification_status == VerificationStatus.PASSED


def test_verifier_manager_handles_crashing_verifier(clean_workspace):
    """Memverifikasi bahwa StepVerificationManager tidak crash jika verifier kustom melempar unhandled exception."""
    manager = StepVerificationManager(clean_workspace)

    class BrokenVerifier:
        def can_verify(self, name): return True
        def verify(self, *a, **kw): raise ZeroDivisionError("Crash tak terduga")

    manager.register_verifier(BrokenVerifier(), priority_first=True)
    # Harus di-handle secara aman dan mengembalikan FAILED atau UNKNOWN, bukan melempar crash
    try:
        res = manager.verify_tool_execution("any_tool", {}, "output")
        assert res.status == VerificationStatus.FAILED
        assert "ZeroDivisionError" in res.evidence
    except ZeroDivisionError:
        pytest.fail("StepVerificationManager tidak menangkap crash internal verifier")


def test_telemetry_consistency_on_failure_and_timeout(clean_workspace):
    """Prioritas 4: Telemetri turn tidak boleh berstatus success jika lifecycle gagal/timeout."""
    agent = Agent(workspace=clean_workspace, llm=InfiniteToolLLM())
    agent.max_steps = 1
    agent.ask("1. Step 1\n2. Step 2")

    # Turn telemetry harus mencatat status error karena timeout
    current_turn = agent.tracer.current_turn
    assert current_turn is not None
    assert current_turn.status == "error"
    assert current_turn.error_message is not None
    assert "Batas langkah" in current_turn.error_message or "tidak tuntas" in current_turn.error_message
