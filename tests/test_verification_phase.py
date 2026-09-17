"""Regression tests: Fase VERIFY berbasis evidence nyata dan integrasi ke lifecycle."""
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from owibot.agent.core import Agent
from owibot.agent.lifecycle import PlanStep, StepStatus
from owibot.agent.verifier import (
    ExecCommandVerifier,
    StepVerificationManager,
    VerificationResult,
    VerificationStatus,
    WriteFileVerifier,
)
from owibot.provider.base import LLMResponse, TokenUsage


class ScriptedVerifyLLM:
    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.model = "mock-verify-llm"
        self.captured_messages: list[list[dict]] = []

    def chat(self, messages, tools=None):
        self.captured_messages.append([dict(m) for m in messages])
        if self.turns:
            step_data = self.turns.pop(0)
            return LLMResponse(
                text=step_data.get("text", ""),
                tool_calls=step_data.get("tool_calls", []),
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model=self.model,
            )
        return LLMResponse(text="Selesai.", model=self.model)


def test_verify_write_file_passed_when_file_exists_on_disk(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    llm = ScriptedVerifyLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "name": "write_file",
                    "arguments": {"path": "hasil.txt", "content": "konten valid"},
                }
            ],
        },
        {"text": "File berhasil dibuat.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="verify_success_chat")
    agent.ask("1. Buat file hasil.txt")

    # 1. Evidence fisik di disk terbukti ada
    file_on_disk = tmp_path / "hasil.txt"
    assert file_on_disk.is_file()
    assert file_on_disk.read_text(encoding="utf-8") == "konten valid"

    # 2. Verifikasi status tersimpan di plan step
    assert hasattr(agent, "last_plan")
    assert len(agent.last_plan) >= 1
    step_1 = agent.last_plan[0]

    assert step_1.status == StepStatus.COMPLETED
    assert step_1.verification_status == VerificationStatus.PASSED
    assert "terverifikasi ada di disk" in step_1.verification_evidence
    assert "hasil.txt" in step_1.verification_evidence


def test_verify_write_file_failed_when_file_missing_on_disk(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Simulasi tool dispatch menghasilkan path yang tidak tercipta
    verifier = WriteFileVerifier()
    res = verifier.verify(
        tool_name="write_file",
        arguments={"path": "file_ghaib.txt", "content": "teks"},
        output="OK: wrote file_ghaib.txt",
        workspace=tmp_path,
    )
    assert res.status == VerificationStatus.FAILED
    assert "tidak ditemukan di disk" in res.evidence


def test_verify_command_exit_code_failed(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Menjalankan command yang gagal terus hingga melampaui batas percobaan recovery
    fail_exec_turn = {
        "text": "",
        "tool_calls": [
            {
                "id": "call_exec",
                "name": "exec",
                "arguments": {"command": "python -c 'import sys; sys.exit(2)'"},
            }
        ],
    }
    llm = ScriptedVerifyLLM([fail_exec_turn, fail_exec_turn, fail_exec_turn, fail_exec_turn])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="verify_fail_exec")
    output = agent.ask("1. Jalankan script error")

    # Sesuai aturan: jika verifikasi gagal melampaui batas percobaan, hentikan lifecycle dengan state jelas
    assert "Tugas dihentikan: Langkah 'step_1' gagal diverifikasi" in output
    assert "non-zero exit code (2)" in output

    assert len(agent.last_plan) >= 1
    failed_step = agent.last_plan[0]
    assert failed_step.status == StepStatus.FAILED
    assert failed_step.verification_status == VerificationStatus.FAILED
    assert "exit code (2)" in failed_step.verification_evidence


def test_verify_tool_reports_success_but_real_objective_not_met(tmp_path):
    # Kasus: output tool mengklaim sukses, tetapi file fisiknya kosong (0 byte) saat diekspetasikan ada konten
    empty_target = tmp_path / "kosong.txt"
    empty_target.write_text("", encoding="utf-8")  # file ada tapi 0 byte

    verifier = WriteFileVerifier()
    res = verifier.verify(
        tool_name="write_file",
        arguments={"path": "kosong.txt", "content": "harus ada data"},
        output="OK: wrote kosong.txt",
        workspace=tmp_path,
    )
    assert res.status == VerificationStatus.FAILED
    assert "kosong (0 byte)" in res.evidence
    assert "tidak terisi sesuai" in res.reason


def test_verification_results_stored_in_plan_steps_and_lifecycle_state(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    llm = ScriptedVerifyLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "write_file",
                    "arguments": {"path": "data.json", "content": '{"status":"ok"}'},
                }
            ],
        },
        {"text": "Pembuatan file tuntas.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="verify_state_chat")
    agent.ask("1. Buat file data.json")

    # Verifikasi state lifecycle dan plan steps
    assert agent.last_lifecycle_state is not None
    state = agent.last_lifecycle_state
    assert len(state.plan_steps) == 1
    assert len(state.verification_notes) >= 1
    assert "PASSED" in state.verification_notes[0]

    step_dict = state.plan_steps[0].to_dict()
    assert step_dict["verification_status"] == "passed"
    assert "terverifikasi ada di disk" in step_dict["verification_evidence"]
    assert "berhasil diverifikasi" in step_dict["verification_reason"]


def test_structured_verify_info_injected_to_conversation(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    llm = ScriptedVerifyLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "list_dir",
                    "arguments": {"path": "."},
                }
            ],
        },
        {"text": "Direktori diperiksa.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="verify_prompt_chat")
    agent.ask("Periksa direktori")

    # Cek pesan percakapan di langkah ke-2
    turn2_messages = llm.captured_messages[1]
    verify_system_msgs = [
        m.get("content", "")
        for m in turn2_messages
        if m.get("role") == "system" and "[Phase: Verify" in m.get("content", "")
    ]
    assert len(verify_system_msgs) >= 1
    first_verify_msg = verify_system_msgs[0]
    assert "• Target:" in first_verify_msg
    assert "• Evidence:" in first_verify_msg
    assert "• Evaluasi:" in first_verify_msg
