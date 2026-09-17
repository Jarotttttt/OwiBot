"""Test Telegram rich messaging, buttons, dan send progress."""
from unittest.mock import MagicMock
from pathlib import Path
import pytest

from owibot.agent.core import Agent, format_tool_progress
from owibot.channels.telegram import (
    create_quick_actions_keyboard,
    split_into_chunks,
)


def test_quick_actions_keyboard():
    keyboard = create_quick_actions_keyboard()
    assert keyboard.inline_keyboard is not None
    callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "action:new" in callbacks
    assert "action:status" in callbacks
    assert "action:help" in callbacks


def test_format_tool_progress():
    assert "Membaca file" in format_tool_progress("read_file", {"path": "test.txt"})
    assert "Menulis file" in format_tool_progress("write_file", {"path": "test.txt"})
    assert "Menjalankan" in format_tool_progress("exec", {"command": "ls -la"})
    assert "Mengunduh" in format_tool_progress("web_fetch", {"url": "https://example.com"})
    assert "Melihat folder" in format_tool_progress("list_dir", {"path": "projects"})
    assert "Memperbarui memori" in format_tool_progress("update_memory", {})
    assert "Mengatur pengingat" in format_tool_progress("cron_job", {})


def test_split_into_chunks():
    short_text = "Halo dunia"
    assert split_into_chunks(short_text) == [short_text]

    long_text = "baris\n" * 1000
    chunks = split_into_chunks(long_text, max_length=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)


def test_agent_progress_callback(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Instruksi dasar", encoding="utf-8")

    class MockLLM:
        def __init__(self):
            self.model = "mock"
            self.calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "text": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "name": "list_dir",
                            "arguments": {"path": "."},
                        }
                    ],
                }
            return {"text": "Daftar selesai.", "tool_calls": []}

    agent = Agent(workspace=tmp_path, llm=MockLLM())
    progress_updates: list[str] = []

    def record_progress(msg: str):
        progress_updates.append(msg)

    response = agent.ask("Lihat file", context={"on_progress": record_progress})
    assert response == "Daftar selesai."
    assert len(progress_updates) >= 2
    assert any("menganalisis" in p.lower() for p in progress_updates)
    assert any("melihat folder" in p.lower() for p in progress_updates)
