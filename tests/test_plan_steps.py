"""Regression test: Perencanaan stateful, formulasi plan_steps, dan pelacakan eksekusi."""
from pathlib import Path
import pytest

from owibot.agent.core import Agent
from owibot.agent.lifecycle import (
    PlanStep,
    StepStatus,
    formulate_plan_steps,
)
from owibot.provider.base import LLMResponse, TokenUsage


class ScriptedPlanLLM:
    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.model = "mock-plan-llm"

    def chat(self, messages, tools=None):
        if self.turns:
            step_data = self.turns.pop(0)
            return LLMResponse(
                text=step_data.get("text", ""),
                tool_calls=step_data.get("tool_calls", []),
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model=self.model,
            )
        return LLMResponse(text="Semua langkah rencana selesai.", model=self.model)


def test_plan_step_data_model_and_serialization():
    step = PlanStep(
        id="step_1",
        description="Membaca konfigurasi awal",
        status=StepStatus.PENDING,
        result="",
    )
    data = step.to_dict()
    assert data["id"] == "step_1"
    assert data["description"] == "Membaca konfigurasi awal"
    assert data["status"] == "pending"
    assert data["result"] == ""

    # Perbarui status dan hasil
    step.status = StepStatus.IN_PROGRESS
    step.result = "Proses berjalan"
    assert step.to_dict()["status"] == "in_progress"
    assert step.to_dict()["result"] == "Proses berjalan"


def test_formulate_plan_steps_numbered_and_connectors():
    # 1. Kasus bernomor eksplisit
    numbered_prompt = "1. Buat direktori src\n2. Tulis file main.py\n3. Jalankan pengujian"
    steps = formulate_plan_steps(numbered_prompt)
    assert len(steps) == 3
    assert steps[0].id == "step_1"
    assert "Buat direktori" in steps[0].description
    assert steps[1].id == "step_2"
    assert steps[2].id == "step_3"
    assert all(s.status == StepStatus.PENDING for s in steps)

    # 2. Kasus penghubung kata "lalu"
    connector_prompt = "Baca file settings.json lalu periksa database"
    steps_conn = formulate_plan_steps(connector_prompt)
    assert len(steps_conn) == 2
    assert "Baca file settings.json" in steps_conn[0].description
    assert "periksa database" in steps_conn[1].description

    # 3. Kasus heuristik tugas kompleks
    complex_prompt = "Buatkan sistem pencatatan transaksi kasir"
    steps_complex = formulate_plan_steps(complex_prompt)
    assert len(steps_complex) == 3
    assert steps_complex[0].id == "step_1"
    assert steps_complex[1].id == "step_2"
    assert steps_complex[2].id == "step_3"


def test_runtime_executes_and_updates_plan_steps_statefully(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Siapkan script respons LLM bertahap:
    # Turn 1: eksekusi step 1 (list_dir)
    # Turn 2: eksekusi step 2 (write_file)
    # Turn 3: finalisasi rencana
    llm = ScriptedPlanLLM([
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
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c2",
                    "name": "write_file",
                    "arguments": {"path": "output.txt", "content": "konten langkah 2"},
                }
            ],
        },
        {"text": "Semua tahap rencana berhasil dituntaskan.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="plan_runtime_chat")
    user_prompt = "1. Periksa folder kerja\n2. Tulis berkas output.txt"

    response = agent.ask(user_prompt)
    assert "Semua tahap rencana berhasil dituntaskan" in response

    # Verifikasi bahwa runtime benar-benar mengisi dan memperbarui stateful plan_steps
    assert hasattr(agent, "last_plan")
    last_plan = agent.last_plan
    assert len(last_plan) == 2

    step_1 = last_plan[0]
    assert step_1.id == "step_1"
    assert step_1.status == StepStatus.COMPLETED
    assert "list_dir" in step_1.result

    step_2 = last_plan[1]
    assert step_2.id == "step_2"
    assert step_2.status == StepStatus.COMPLETED
    assert "write_file" in step_2.result
    assert (tmp_path / "output.txt").is_file()


def test_runtime_marks_failed_plan_step_on_tool_error(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi", encoding="utf-8")

    # Step 1 gagal mengeksekusi file yang tidak ada
    llm = ScriptedPlanLLM([
        {
            "text": "",
            "tool_calls": [
                {
                    "id": "c_fail",
                    "name": "read_file",
                    "arguments": {"path": "berkas_palsu.txt"},
                }
            ],
        },
        {"text": "Langkah 1 gagal.", "tool_calls": []},
    ])

    agent = Agent(workspace=tmp_path, llm=llm, chat_id="plan_fail_chat")
    agent.ask("1. Baca berkas palsu")

    last_plan = agent.last_plan
    assert len(last_plan) >= 1
    # Step yang memanggil tool error memiliki catatan hasil error
    assert "read_file" in last_plan[0].result
    assert "ERROR" in last_plan[0].result
