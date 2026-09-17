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


# ==============================================================================
# REGRESSION TESTS: BATCH TOOL-CALL MAPPING & TEXT-ONLY / FINALIZATION PATH
# ==============================================================================

class ScriptedLifecycleLLM:
    """Mock LLM dengan daftar respons bertahap."""
    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.model = "mock-scripted"

    def chat(self, messages, tools=None):
        if self.turns:
            step = self.turns.pop(0)
            return LLMResponse(
                text=step.get("text", ""),
                tool_calls=step.get("tool_calls", []),
                model=self.model,
            )
        return LLMResponse(text="Selesai.", model=self.model)


def test_batch_mapping_two_tools_to_two_different_steps(clean_workspace):
    """2 tool call dalam 1 batch harus dipetakan ke 2 step berbeda secara unik."""
    llm = ScriptedLifecycleLLM([
        {
            "text": "",
            "tool_calls": [
                {"id": "c1", "name": "write_file", "arguments": {"path": "alpha.txt", "content": "AAA"}},
                {"id": "c2", "name": "write_file", "arguments": {"path": "beta.txt", "content": "BBB"}},
            ],
        },
        {"text": "Semua selesai.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    agent.ask("1. Tulis file alpha.txt\n2. Tulis file beta.txt")

    assert len(agent.last_plan) == 2
    step_1 = agent.last_plan[0]
    step_2 = agent.last_plan[1]

    assert step_1.status == StepStatus.COMPLETED
    assert step_2.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED
    assert step_2.verification_status == VerificationStatus.PASSED

    assert "alpha.txt" in step_1.verification_evidence
    assert "beta.txt" not in step_1.verification_evidence
    assert "beta.txt" in step_2.verification_evidence
    assert "alpha.txt" not in step_2.verification_evidence


def test_batch_mapping_identical_tools_not_silently_mapped_to_same_step(clean_workspace):
    """2 tool call identik dalam 1 batch tidak boleh diam-diam masuk ke step yang sama atau mencemari step lain."""
    llm = ScriptedLifecycleLLM([
        {
            "text": "",
            "tool_calls": [
                {"id": "c1", "name": "write_file", "arguments": {"path": "alpha.txt", "content": "AAA1"}},
                {"id": "c2", "name": "write_file", "arguments": {"path": "alpha.txt", "content": "AAA2"}},
            ],
        },
        {"text": "Selesai.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    agent.ask("1. Tulis file alpha.txt\n2. Tulis file beta.txt")

    assert len(agent.last_plan) == 2
    step_1 = agent.last_plan[0]
    step_2 = agent.last_plan[1]

    # Step 1 menerima c1 dan terverifikasi sukses
    assert step_1.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED
    assert "alpha.txt" in step_1.verification_evidence

    # Step 2 tidak boleh menerima call c2 yang menargetkan alpha.txt
    assert step_2.status != StepStatus.COMPLETED
    assert step_2.verification_status != VerificationStatus.PASSED
    assert step_2.status == StepStatus.FAILED
    assert "alpha.txt" not in step_2.verification_evidence

    # Turn telemetri berstatus error karena step 2 tidak terselesaikan
    assert agent.tracer.current_turn.status == "error"


def test_batch_mapping_unmappable_tool_safe_without_corrupting_state(clean_workspace):
    """Tool call tanpa target yang cocok berstatus unmapped tanpa merusak state PlanStep."""
    llm = ScriptedLifecycleLLM([
        {
            "text": "",
            "tool_calls": [
                {"id": "c1", "name": "write_file", "arguments": {"path": "alpha.txt", "content": "konten"}},
                {"id": "c2", "name": "exec", "arguments": {"command": "echo unmappable_action"}},
            ],
        },
        {"text": "Selesai.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    agent.ask("1. Tulis file alpha.txt\n2. Tulis file beta.txt")

    step_1 = agent.last_plan[0]
    step_2 = agent.last_plan[1]

    # Step 1 terverifikasi dengan benar
    assert step_1.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED

    # Step 2 tidak boleh dicemari oleh eksekusi exec unmappable
    assert "unmappable_action" not in step_2.result
    assert step_2.status == StepStatus.FAILED
    assert step_2.verification_status != VerificationStatus.PASSED

    # Verifikasi dicatat sebagai unmapped di catatan lifecycle
    assert any("unmapped" in note.lower() for note in agent.last_lifecycle_state.verification_notes)


def test_batch_mapping_remains_correct_during_step_recovery(clean_workspace):
    """Batch mapping tetap bekerja benar dan terisolasi saat salah satu step masuk RECOVER."""
    llm = ScriptedLifecycleLLM([
        # Turn 1: Step 1 memanggil read_file yang gagal karena file tidak ada
        {
            "text": "",
            "tool_calls": [
                {"id": "c_fail", "name": "read_file", "arguments": {"path": "step1.txt"}},
            ],
        },
        # Turn 2: Batch pemulihan Step 1 dan eksekusi Step 2 secara simultan
        {
            "text": "",
            "tool_calls": [
                {"id": "c_fix", "name": "write_file", "arguments": {"path": "step1.txt", "content": "konten langkah 1"}},
                {"id": "c_step2", "name": "write_file", "arguments": {"path": "step2.txt", "content": "konten langkah 2"}},
            ],
        },
        {"text": "Rencana sukses setelah recovery.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    agent.ask("1. Tangani file step1.txt\n2. Tangani file step2.txt")

    step_1 = agent.last_plan[0]
    step_2 = agent.last_plan[1]

    # Kedua step harus COMPLETED dan PASSED dengan evidence masing-masing
    assert step_1.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED
    assert "step1.txt" in step_1.verification_evidence
    assert "step2.txt" not in step_1.verification_evidence

    assert step_2.status == StepStatus.COMPLETED
    assert step_2.verification_status == VerificationStatus.PASSED
    assert "step2.txt" in step_2.verification_evidence
    assert "step1.txt" not in step_2.verification_evidence

    # Riwayat recovery step 1 tercatat dan turn sukses
    state = agent.last_lifecycle_state
    assert len(state.recovery_history) >= 1
    assert state.recovery_history[0].failed_step_id == "step_1"
    assert state.recovery_history[0].verification_result == "passed"
    assert agent.tracer.current_turn.status == "success"


def test_conversational_prompt_without_tool_normal_response_no_fake_evidence(clean_workspace):
    """Conversational prompt tanpa tool menghasilkan response normal tanpa evidence palsu verifier."""
    llm = ScriptedLifecycleLLM([
        {"text": "Halo! Saya OwiBot, siap membantu Anda.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    res = agent.ask("Halo apa kabar?")

    assert "Halo! Saya OwiBot" in res
    step = agent.last_plan[0]
    assert step.status == StepStatus.COMPLETED
    # Tidak boleh ada evidence palsu yang seolah dari verifier
    assert step.verification_evidence == ""
    assert step.verification_status != VerificationStatus.PASSED
    assert step.verification_status == VerificationStatus.UNKNOWN
    assert agent.tracer.current_turn.status == "success"


def test_execution_task_without_tool_call_not_success(clean_workspace):
    """Execution task yang dijawab teks saja tanpa tool call tidak boleh dianggap sukses."""
    llm = ScriptedLifecycleLLM([
        {"text": "Saya sudah selesai membuat berkas target.txt.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    res = agent.ask("1. Buat berkas target.txt")

    step = agent.last_plan[0]
    assert step.status != StepStatus.COMPLETED
    assert step.status == StepStatus.FAILED
    assert step.verification_status != VerificationStatus.PASSED
    assert step.verification_status == VerificationStatus.FAILED
    assert "tanpa pemanggilan tool" in step.verification_reason.lower()

    # Telemetri turn tidak boleh berstatus success
    assert agent.tracer.current_turn.status == "error"


def test_execution_task_verified_completed_only_after_verifier_passed(clean_workspace):
    """Execution task hanya berstatus COMPLETED setelah verifier nyata menyatakan PASSED."""
    llm = ScriptedLifecycleLLM([
        {
            "text": "",
            "tool_calls": [
                {"id": "c1", "name": "write_file", "arguments": {"path": "riil.txt", "content": "data riil"}},
            ],
        },
        {"text": "Berkas telah dibuat di disk.", "tool_calls": []},
    ])
    agent = Agent(workspace=clean_workspace, llm=llm)
    agent.ask("1. Buat file riil.txt")

    step = agent.last_plan[0]
    assert step.status == StepStatus.COMPLETED
    assert step.verification_status == VerificationStatus.PASSED
    assert "riil.txt" in step.verification_evidence
    assert (clean_workspace / "riil.txt").is_file()
    assert agent.tracer.current_turn.status == "success"


def test_timeout_never_produces_fake_passed(clean_workspace):
    """Timeout tidak pernah menghasilkan status PASSED atau COMPLETED palsu."""
    agent = Agent(workspace=clean_workspace, llm=InfiniteToolLLM())
    agent.max_steps = 1
    agent.ask("1. Tugas pertama berlarut\n2. Tugas kedua tidak sempat")

    assert len(agent.last_plan) == 2
    for step in agent.last_plan:
        assert step.status != StepStatus.COMPLETED
        assert step.verification_status != VerificationStatus.PASSED
        assert step.status == StepStatus.FAILED
        assert step.verification_status == VerificationStatus.FAILED
        assert "timeout" in step.verification_reason.lower()

    assert agent.tracer.current_turn.status == "error"

