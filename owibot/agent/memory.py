from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_MEMORY_CHARS = 3000
MAX_USER_CHARS = 1500


class MemoryStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = workspace / "memory"
        self.history_dir = self.memory_dir / "history"
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.user_file = self.memory_dir / "USER.md"
        self.db_path = self.memory_dir / "sessions.db"

        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file.touch(exist_ok=True)
        self.user_file.touch(exist_ok=True)

        self._fts_enabled = self._init_database()

    def _init_database(self) -> bool:
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT,
                        timestamp TEXT,
                        user_text TEXT,
                        assistant_text TEXT
                    )
                    """
                )
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5 (
                            user_text,
                            assistant_text,
                            content='turns',
                            content_rowid='id'
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
                            INSERT INTO turns_fts(rowid, user_text, assistant_text)
                            VALUES (new.id, new.user_text, new.assistant_text);
                        END
                        """
                    )
                    return True
                except sqlite3.OperationalError:
                    return False
        except Exception:
            return False

    def read_memory(self) -> str:
        if not self.memory_file.exists():
            return ""
        return self.memory_file.read_text(encoding="utf-8")

    def read_user_profile(self) -> str:
        if not self.user_file.exists():
            return ""
        return self.user_file.read_text(encoding="utf-8")

    def update_memory(self, content: str) -> str:
        text = (content or "").strip()
        if not text:
            return "ERROR: Konten memori tidak boleh kosong."

        if len(text) > MAX_MEMORY_CHARS:
            text = text[:MAX_MEMORY_CHARS] + "\n... (dipotong sesuai batas kapasitas)"

        self.memory_file.write_text(text + "\n", encoding="utf-8")
        return f"OK: MEMORY.md diperbarui ({len(text)} karakter)"

    def append_memory_item(self, category: str, item: str) -> str:
        clean_item = (item or "").strip()
        if not clean_item:
            return "ERROR: Catatan tidak boleh kosong."

        clean_cat = (category or "FACT").upper().strip()
        new_entry = f"- [{clean_cat}] {clean_item}"

        current_content = self.read_memory()
        if clean_item.lower() in current_content.lower():
            return "OK: Catatan serupa sudah ada di memori."

        updated = (current_content.strip() + "\n" + new_entry).strip() + "\n"
        if len(updated) > MAX_MEMORY_CHARS:
            return f"ERROR: Memori hampir penuh ({len(current_content)}/{MAX_MEMORY_CHARS} char). Silakan konsolidasi memori terlebih dahulu."

        self.memory_file.write_text(updated, encoding="utf-8")
        return f"OK: Memori ditambahkan ({clean_cat}): {clean_item}"

    def update_user_profile(self, profile_text: str) -> str:
        clean_text = (profile_text or "").strip()
        if len(clean_text) > MAX_USER_CHARS:
            clean_text = clean_text[:MAX_USER_CHARS]

        self.user_file.write_text(clean_text + "\n", encoding="utf-8")
        return f"OK: USER.md diperbarui ({len(clean_text)} karakter)"

    def append_turn(self, user_text: str, assistant_text: str, chat_id: str = "default") -> None:
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Simpan ke file JSONL (arsip tanggal)
        record = {
            "timestamp": ts,
            "chat_id": chat_id,
            "user": user_text.strip(),
            "assistant": assistant_text.strip(),
        }
        log_file = self.history_dir / f"{now.strftime('%Y-%m-%d')}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 2. Indeks ke SQLite FTS5 database
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO turns (chat_id, timestamp, user_text, assistant_text) VALUES (?, ?, ?, ?)",
                    (chat_id, ts, user_text.strip(), assistant_text.strip()),
                )
        except Exception:
            pass

    def search_history(self, query: str, limit: int = 5, chat_id: str | None = None) -> list[str]:
        keyword = (query or "").strip()
        if not keyword:
            return []

        # 1. Coba pencarian dengan SQLite FTS5
        if self._fts_enabled:
            results = self._search_fts(keyword, limit=limit, chat_id=chat_id)
            if results:
                return results

        # 2. Fallback pencarian JSONL linear scan
        return self._search_jsonl_scan(keyword, limit=limit)

    def _search_fts(self, query: str, limit: int = 5, chat_id: str | None = None) -> list[str]:
        try:
            import re
            words = [re.sub(r"[^\w]", "", w) for w in query.split()]
            valid_words = [w for w in words if w]
            if not valid_words:
                return []

            # Mencari token dengan boolean AND di FTS5
            fts_query = " AND ".join(f'"{w}"*' for w in valid_words)

            with sqlite3.connect(str(self.db_path)) as conn:
                if chat_id:
                    cursor = conn.execute(
                        """
                        SELECT turns.timestamp, turns.user_text, turns.assistant_text
                        FROM turns
                        JOIN turns_fts ON turns.id = turns_fts.rowid
                        WHERE turns_fts MATCH ? AND turns.chat_id = ?
                        ORDER BY turns.id DESC LIMIT ?
                        """,
                        (fts_query, chat_id, limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT turns.timestamp, turns.user_text, turns.assistant_text
                        FROM turns
                        JOIN turns_fts ON turns.id = turns_fts.rowid
                        WHERE turns_fts MATCH ?
                        ORDER BY turns.id DESC LIMIT ?
                        """,
                        (fts_query, limit),
                    )
                rows = cursor.fetchall()
                return [
                    f"[{ts}]\nUser: {u[:400]}\nAssistant: {a[:600]}"
                    for ts, u, a in reversed(rows)
                ]
        except Exception:
            return []

    def _search_jsonl_scan(self, keyword: str, limit: int = 5) -> list[str]:
        matched_entries: list[str] = []
        lowered = keyword.lower()

        for file_path in sorted(self.history_dir.glob("*.jsonl")):
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            for line in content.splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    ts = str(data.get("timestamp", data.get("ts", ""))).strip()
                    user = str(data.get("user", "")).strip()
                    assistant = str(data.get("assistant", "")).strip()
                except (json.JSONDecodeError, AttributeError):
                    continue

                formatted_entry = f"[{ts}]\nUser: {user}\nAssistant: {assistant}"
                if lowered in formatted_entry.lower():
                    matched_entries.append(formatted_entry)

        return matched_entries[-limit:][::-1]

    def get_memory_stats(self) -> dict[str, Any]:
        total_turns = 0
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM turns")
                row = cursor.fetchone()
                total_turns = int(row[0]) if row else 0
        except Exception:
            pass

        return {
            "total_indexed_turns": total_turns,
            "memory_chars": len(self.read_memory()),
            "memory_limit": MAX_MEMORY_CHARS,
            "user_chars": len(self.read_user_profile()),
            "user_limit": MAX_USER_CHARS,
            "fts5_active": self._fts_enabled,
        }
