"""Regression test: Memastikan isolasi sesi chat_id pada TelegramGateway & FTS5 memory."""
from pathlib import Path
import pytest

from owibot.agent.core import Agent
from owibot.channels.telegram import TelegramGateway, TelegramSettings
from owibot.provider.base import LLMResponse, TokenUsage


class ScriptedLLM:
    def __init__(self, reply: str = "Jawaban default"):
        self.reply = reply
        self.model = "mock-model"

    def chat(self, messages, tools=None):
        return LLMResponse(
            text=self.reply,
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model=self.model,
        )


def test_telegram_gateway_agent_creation_chat_id_binding(tmp_path):
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Aturan OwiBot", encoding="utf-8")

    llm = ScriptedLLM()

    def factory(cid="default"):
        return Agent(workspace=tmp_path, llm=llm, chat_id=cid)

    cron_file = tmp_path / "cron.json"
    gateway = TelegramGateway(
        settings=TelegramSettings(token="dummy:token", allow_from=["111", "222"]),
        agent_factory=factory,
        cron_path=cron_file,
    )

    # 1. Pastikan get_agent_for_chat mengikat chat_id yang benar
    agent_111 = gateway.get_agent_for_chat("111")
    agent_222 = gateway.get_agent_for_chat("222")

    assert agent_111.chat_id == "111"
    assert agent_222.chat_id == "222"
    assert agent_111 is not agent_222

    # 2. Eksekusi percakapan di masing-masing sesi
    agent_111.llm.reply = "Rahasia user 111: token_merah"
    agent_111.ask("Sesi 111 rahasia")

    agent_222.llm.reply = "Rahasia user 222: token_biru"
    agent_222.ask("Sesi 222 rahasia")

    # 3. Verifikasi isolasi pencarian riwayat obrolan (FTS5 / history)
    history_111 = agent_111.memory.search_history("token", chat_id="111")
    history_222 = agent_222.memory.search_history("token", chat_id="222")

    assert len(history_111) >= 1
    assert "token_merah" in history_111[0]
    assert "token_biru" not in history_111[0]

    assert len(history_222) >= 1
    assert "token_biru" in history_222[0]
    assert "token_merah" not in history_222[0]

    # 4. Verifikasi reset sesi tetap mengikat chat_id yang tepat
    new_agent_111 = gateway._create_agent("111")
    assert new_agent_111.chat_id == "111"
