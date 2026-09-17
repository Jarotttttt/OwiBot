"""Test Layered Memory System: Long-term curated + SQLite FTS5 Session Search."""
import json
from pathlib import Path
import pytest

from owibot.agent.memory import MemoryStore
from owibot.agent.tools import LocalTools


def test_memory_store_curated_facts(tmp_path):
    store = MemoryStore(tmp_path)
    res = store.append_memory_item("RULE", "Gunakan tab alih-alih spasi")
    assert "OK" in res
    assert "[RULE] Gunakan tab alih-alih spasi" in store.read_memory()

    # Deduplikasi
    res_dup = store.append_memory_item("RULE", "Gunakan tab alih-alih spasi")
    assert "sudah ada" in res_dup


def test_memory_user_profile(tmp_path):
    store = MemoryStore(tmp_path)
    store.update_user_profile("User adalah senior Python engineer di Jakarta (WIB).")
    assert "senior Python engineer" in store.read_user_profile()


def test_session_turns_fts5_indexing_and_search(tmp_path):
    store = MemoryStore(tmp_path)

    store.append_turn(
        user_text="Bagaimana cara konfigurasi database Postgres?",
        assistant_text="Gunakan konfigurasi DATABASE_URL di file .env.",
        chat_id="chat_dev_1",
    )
    store.append_turn(
        user_text="Cuaca hari ini cerah sekali.",
        assistant_text="Bagus, jangan lupa minum air putih.",
        chat_id="chat_dev_1",
    )

    # Cari dengan query spesifik
    results = store.search_history("Postgres database", chat_id="chat_dev_1")
    assert len(results) >= 1
    assert "DATABASE_URL" in results[0]

    # Cek statistik memori
    stats = store.get_memory_stats()
    assert stats["total_indexed_turns"] == 2
    assert stats["fts5_active"] is True


def test_local_tools_session_search(tmp_path):
    tools = LocalTools(tmp_path)
    store = MemoryStore(tmp_path)
    store.append_turn("Kunci deployment", "Password token adalah secret_deploy_99", chat_id="c1")

    tools.set_context({"chat_id": "c1"})
    search_output = tools.session_search("Kunci deployment")
    assert "secret_deploy_99" in search_output
