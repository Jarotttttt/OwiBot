"""Regression tests: Fase RECOVER berbasis bukti kegagalan dan pencegahan infinite loop."""
from pathlib import Path
import pytest

from owibot.agent.core import Agent
from owibot.agent.lifecycle import PlanStep, StepStatus
from owibot.agent.recovery import (
    CommandFailureStrategy,
    FileMissingStrategy,
    RecoveryManager,
    RecoveryFailureType,
)
from owibot.agent.verifier import VerificationResult, VerificationStatus
from owibot.provider.base import LLMResponse, TokenUsage


class ScriptedRecoveryLLM:
    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.model = "mock-recovery-llm"
        self.captured_prompts: list[list[dict]] = []

    def chat(self, messages, tools=None):
        self.captured_prompts.append([dict(m) for m in messages])
        if self.turns:
            step_data = self.turns.pop(0)
            return LLMResponse(
                text=step_data.get("text", ""),
                tool_calls=step_data.get("tool_calls", []),
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model=self.model,
            )
        return LLMResponse(text="Semua proses selesai.", model=self.model)


def test_recovery_fixes_failure_and_verify_passes(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Turn 1: Gagal membaca file yang tidak ada -> VERIFY FAILED -> RECOVER
    # Turn 2: LLM mengikuti arahan korektif, membuat file -> VERIFY PASSED -> COMPLETED
    # Turn 3: LLM finalisasi
    llm = ScriptedRecoveryLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c_fail",
                    "name": "read_file",
                    "arguments": {"path": "hilang.txt"},
                }
            ],
        },
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c_fix",
                    "name": "write_file",
                    "arguments": {"path": "hilang.txt", "content": "konten perbaikan"},
                }
            ],
        },
        {"text": "Masalah file teratasi.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="recover_fix_chat")
    progress_log: list[str] = []

    result = agent.ask("1. Kelola file hilang.txt", context={"on_progress": lambda m: progress_log.append(m)})
    assert "Masalah file teratasi" in result

    # 1. Step berakhir dengan COMPLETED setelah verifikasi passed
    assert len(agent.last_plan) >= 1
    step_1 = agent.last_plan[0]
    assert step_1.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED

    # 2. History recovery tercatat
    state = agent.last_lifecycle_state
    assert len(state.recovery_history) == 1
    attempt = state.recovery_history[0]
    assert attempt.failed_step_id == "step_1"
    assert "tidak ditemukan" in attempt.previous_evidence or "read_file" in attempt.reason
    assert attempt.verification_result == "passed"


def test_recovery_retries_with_different_strategies_across_attempts(tmp_path):
    mgr = RecoveryManager()
    vr = VerificationResult(
        status=VerificationStatus.FAILED,
        evidence="Perintah selesai dengan non-zero exit code (127). Stderr: command not found",
        reason="Proses terminal mengembalikan error.",
        verified_target="exec(bad_cmd)",
    )

    # Percobaan 1: Strategi evaluasi argumen
    att1 = mgr.create_recovery_attempt(1, "step_1", None, vr, None)
    # Percobaan 2: Strategi alternatif / pemecahan perintah
    att2 = mgr.create_recovery_attempt(2, "step_1", None, vr, None)
    # Percobaan 3: Strategi pendekatan pengganti
    att3 = mgr.create_recovery_attempt(3, "step_1", None, vr, None)

    assert att1.corrective_action != att2.corrective_action
    assert att2.corrective_action != att3.corrective_action
    assert "non-zero exit code" in att1.previous_evidence


def test_max_3_recovery_attempts_and_no_infinite_loop(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # LLM gagal 5 kali berturut-turut pada tool yang sama
    fail_turn = {
        "text": "",
        "tool_calls": [
            {
                "id": "c_fail",
                "name": "read_file",
                "arguments": {"path": "palsu.txt"},
            }
        ],
    }
    llm = ScriptedRecoveryLLM([fail_turn, fail_turn, fail_turn, fail_turn, fail_turn])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="recover_max_chat")
    output = agent.ask("1. Baca file palsu")

    # 1. Hentikan lifecycle dengan pesan yang jelas
    assert "Tugas dihentikan" in output
    assert "setelah 3 kali percobaan pemulihan" in output

    # 2. Maksimal tepat 3 percobaan recovery tercatat (tidak ada infinite loop)
    state = agent.last_lifecycle_state
    assert len(state.recovery_history) == 3
    assert state.step_recovery_counts.get("step_1") == 4  # Percobaan ke-4 ditolak karena > 3

    # 3. Step ditandai FAILED secara permanen
    assert state.plan_steps[0].status == StepStatus.FAILED


def test_step_only_completed_after_verification_passed(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Gagal di turn 1, sukses di turn 2
    llm = ScriptedRecoveryLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "read_file",
                    "arguments": {"path": "target.txt"},
                }
            ],
        },
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c2",
                    "name": "write_file",
                    "arguments": {"path": "target.txt", "content": "berhasil"},
                }
            ],
        },
        {"text": "Selesai.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="verify_only_passed")
    agent.ask("1. Tangani target.txt")

    step = agent.last_plan[0]
    assert step.status == StepStatus.COMPLETED
    assert step.verification_status == VerificationStatus.PASSED


def test_recovery_history_stored_in_lifecycle_state(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    llm = ScriptedRecoveryLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c_err",
                    "name": "exec",
                    "arguments": {"command": "python -c 'import sys; sys.exit(5)'"},
                }
            ],
        },
        {"text": "Gagal.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="rec_history_chat")
    agent.ask("1. Jalankan proses error")

    state = agent.last_lifecycle_state
    assert len(state.recovery_history) >= 1
    rec = state.recovery_history[0]

    # Validasi semua field yang dipersyaratkan ada
    data = rec.to_dict()
    assert "attempt_id" in data
    assert "failed_step_id" in data
    assert "reason" in data
    assert "previous_evidence" in data
    assert "corrective_action" in data
    assert "result" in data
    assert "verification_result" in data
    assert data["failed_step_id"] == "step_1"
    assert "exit code (5)" in data["previous_evidence"]
