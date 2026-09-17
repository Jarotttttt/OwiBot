"""Hermes-style memory: bounded MEMORY.md + USER.md, SQLite FTS5 session search.

Layout (inside workspace/memory/):
  MEMORY.md      agent notes, max 2200 chars, entries joined by §
  USER.md        user profile, max 1375 chars, entries joined by §
  sessions.db    every turn, FTS5-indexed (session_search backend)
  history/       daily JSONL log (kept for backward compatibility)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

MEMORY_BUDGET = 2200
USER_BUDGET = 1375
DELIM = "§"


def _parse_entries(text: str) -> list[str]:
    """Split stored file into entries. Understands §-joined files and legacy
    free-form markdown (one entry per non-empty, non-header line)."""
    text = (text or "").strip()
    if not text:
        return []
    if DELIM in text:
        return [e.strip() for e in text.split(DELIM) if e.strip()]
    entries = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*0123456789. ").strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def _render(entries: list[str]) -> str:
    return (f" {DELIM} ".join(entries) + "\n") if entries else ""


class MemoryError(ValueError):
    pass


class MemoryStore:
    def __init__(self, workspace: Path):
        self.dir = workspace / "memory"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.dir / "MEMORY.md"
        self.user_path = self.dir / "USER.md"
        self.history_dir = self.dir / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path.touch(exist_ok=True)
        self.user_path.touch(exist_ok=True)
        self.db_path = self.dir / "sessions.db"
        self._fts_ok = self._init_db()

    # -- file helpers ---------------------------------------------------
    def _paths(self, target: str) -> tuple[Path, int, str]:
        t = (target or "").strip().lower()
        if t in {"memory", "memories", "mem"}:
            return self.memory_path, MEMORY_BUDGET, "MEMORY.md"
        if t in {"user", "profile"}:
            return self.user_path, USER_BUDGET, "USER.md"
        raise MemoryError("target must be 'memory' or 'user'")

    def entries(self, target: str) -> list[str]:
        path, _, _ = self._paths(target)
        return _parse_entries(path.read_text(encoding="utf-8"))

    def usage(self, target: str) -> str:
        path, budget, _ = self._paths(target)
        n = len(path.read_text(encoding="utf-8").rstrip("\n"))
        return f"{n}/{budget} chars ({n * 100 // budget if budget else 0}%)"

    def snapshot(self) -> str:
        """Frozen block for the system prompt (Hermes-style header + § entries)."""
        blocks = []
        for target, label in (("memory", "MEMORY (agent notes)"), ("user", "USER PROFILE")):
            path, budget, _ = self._paths(target)
            raw = path.read_text(encoding="utf-8").rstrip("\n")
            n = len(raw)
            body = raw if raw else "(empty)"
            blocks.append(
                f"══ {label} [{n * 100 // budget}% — {n}/{budget} chars] ══\n{body}"
            )
        return "\n\n".join(blocks)

    # -- memory tool actions (Hermes semantics) --------------------------
    def add(self, target: str, content: str) -> str:
        entry = " ".join((content or "").split())
        if not entry:
            raise MemoryError("content is empty")
        if len(entry) > 500:
            raise MemoryError("entry too long (max 500 chars); split it into smaller facts")
        path, budget, label = self._paths(target)
        current = self.entries(target)
        norm = entry.lower()
        if any(e.lower() == norm for e in current):
            return f"OK: no duplicate added ({label} unchanged)"
        trial = _render(current + [entry]).rstrip("\n")
        if len(trial) > budget:
            raise MemoryError(
                f"{label} at {self.usage(target)}. Adding this entry ({len(entry)} chars) "
                f"would exceed the limit. Consolidate now: use action=replace to merge "
                f"overlapping entries into shorter ones or action=remove for stale entries, "
                f"then retry — all in this turn.\nCurrent entries:\n"
                + "\n".join(f"- {e}" for e in current)
            )
        path.write_text(trial + "\n", encoding="utf-8")
        return f"OK: added to {label} ({self.usage(target)})"

    def _match(self, current: list[str], old_text: str) -> int:
        needle = " ".join((old_text or "").split()).lower()
        if not needle:
            raise MemoryError("old_text is empty")
        hits = [i for i, e in enumerate(current) if needle in e.lower()]
        if not hits:
            raise MemoryError(f"no entry matches '{old_text}'")
        if len(hits) > 1:
            raise MemoryError(
                f"'{old_text}' matches {len(hits)} entries; be more specific:\n"
                + "\n".join(f"- {current[i]}" for i in hits)
            )
        return hits[0]

    def replace(self, target: str, old_text: str, content: str) -> str:
        entry = " ".join((content or "").split())
        if not entry:
            raise MemoryError("content is empty")
        path, budget, label = self._paths(target)
        current = self.entries(target)
        idx = self._match(current, old_text)
        trial = _render([*current[:idx], entry, *current[idx + 1:]]).rstrip("\n")
        if len(trial) > budget:
            raise MemoryError(
                f"replacement would exceed {label} limit ({self.usage(target)}). "
                "Shorten the new content or remove another entry first."
            )
        path.write_text(trial + "\n", encoding="utf-8")
        return f"OK: replaced in {label} ({self.usage(target)})"

    def remove(self, target: str, old_text: str) -> str:
        path, _, label = self._paths(target)
        current = self.entries(target)
        idx = self._match(current, old_text)
        gone = current.pop(idx)
        path.write_text(_render(current), encoding="utf-8")
        return f"OK: removed from {label}: {gone[:120]}"

    # -- session log (JSONL + SQLite FTS5) -------------------------------
    def _init_db(self) -> bool:
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute(
                "CREATE TABLE IF NOT EXISTS turns"
                " (id INTEGER PRIMARY KEY, ts TEXT, chat TEXT, user_text TEXT, assistant_text TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS meta (chat TEXT, key TEXT, value TEXT,"
                " PRIMARY KEY (chat, key))"
            )
            try:
                con.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5"
                    "(user_text, assistant_text, content='turns', content_rowid='id')"
                )
                con.execute(
                    "CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN "
                    "INSERT INTO turns_fts(rowid, user_text, assistant_text) "
                    "VALUES (new.id, new.user_text, new.assistant_text); END"
                )
                fts = True
            except sqlite3.OperationalError:
                fts = False
            con.commit()
            con.close()
            return fts
        except Exception:
            return False

    def append_turn(self, user_text: str, assistant_text: str, chat: str = "default") -> None:
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M")
        row = {"ts": ts, "chat": chat, "user": user_text.strip(), "assistant": assistant_text.strip()}
        with (self.history_dir / f"{now.strftime('%Y-%m-%d')}.jsonl").open(
            "a", encoding="utf-8"
        ) as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute(
                "INSERT INTO turns (ts, chat, user_text, assistant_text) VALUES (?, ?, ?, ?)",
                (ts, chat, row["user"], row["assistant"][:2000]),
            )
            con.commit()
            con.close()
        except Exception:
            pass

    def search_history(self, query: str, k: int = 5, chat: str | None = None) -> list[str]:
        query = (query or "").strip()
        if not query:
            return []
        if self._fts_ok:
            hits = self._search_fts(query, k, chat)
            if hits:
                return hits
        return self._search_scan(query, k, chat)

    def _search_fts(self, query: str, k: int, chat: str | None) -> list[str]:
        try:
            phrase = '"' + query.replace('"', '""') + '"'
            con = sqlite3.connect(str(self.db_path))
            if chat:
                rows = con.execute(
                    "SELECT ts, user_text, assistant_text FROM turns "
                    "JOIN turns_fts ON turns.id = turns_fts.rowid "
                    "WHERE turns_fts MATCH ? AND turns.chat = ? "
                    "ORDER BY turns.id DESC LIMIT ?",
                    (phrase, chat, k),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT ts, user_text, assistant_text FROM turns "
                    "JOIN turns_fts ON turns.id = turns_fts.rowid "
                    "WHERE turns_fts MATCH ? ORDER BY turns.id DESC LIMIT ?",
                    (phrase, k),
                ).fetchall()
            con.close()
            return [f"[{ts}]\nUSER: {u[:500]}\nASSISTANT: {a[:800]}" for ts, u, a in rows][::-1]
        except Exception:
            return []

    def _search_scan(self, query: str, k: int, chat: str | None) -> list[str]:
        needle = query.lower()
        hits: list[str] = []
        for p in sorted(self.history_dir.glob("*.jsonl")):
            for raw in p.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if chat and str(row.get("chat", "default")) != chat:
                    continue
                block = (
                    f"[{row.get('ts', '')}]\nUSER: {row.get('user', '')}\n"
                    f"ASSISTANT: {row.get('assistant', '')}"
                )
                if needle in block.lower():
                    hits.append(block)
        return hits[-k:][::-1]

    # -- meta (per-chat settings like model override) --------------------
    def save_meta(self, chat: str, key: str, value: str) -> None:
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute(
                "INSERT INTO meta (chat, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT (chat, key) DO UPDATE SET value = excluded.value",
                (chat, key, value),
            )
            con.commit()
            con.close()
        except Exception:
            pass

    def load_meta(self, chat: str, key: str) -> str:
        try:
            con = sqlite3.connect(str(self.db_path))
            row = con.execute(
                "SELECT value FROM meta WHERE chat = ? AND key = ?", (chat, key)
            ).fetchone()
            con.close()
            return str(row[0]) if row else ""
        except Exception:
            return ""

    def recent_prompts(self, chat: str, k: int = 5) -> list[str]:
        try:
            con = sqlite3.connect(str(self.db_path))
            rows = con.execute(
                "SELECT ts, user_text FROM turns WHERE chat = ? "
                "ORDER BY id DESC LIMIT ?",
                (chat, k),
            ).fetchall()
            con.close()
            return [f"[{ts}] {u[:80]}" for ts, u in rows][::-1]
        except Exception:
            return []

    def stats(self, chat: str | None = None) -> dict:
        turns, chars = 0, 0
        try:
            con = sqlite3.connect(str(self.db_path))
            if chat:
                row = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(LENGTH(user_text) + LENGTH(assistant_text)), 0)"
                    " FROM turns WHERE chat = ?",
                    (chat,),
                ).fetchone()
            else:
                row = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(LENGTH(user_text) + LENGTH(assistant_text)), 0)"
                    " FROM turns"
                ).fetchone()
            con.close()
            turns, chars = int(row[0] or 0), int(row[1] or 0)
        except Exception:
            pass
        return {
            "turns": turns,
            "chars": chars,
            "memory": self.usage("memory"),
            "user": self.usage("user"),
        }

    # -- backward compat --------------------------------------------------
    def read_memory(self) -> str:
        return self.memory_path.read_text(encoding="utf-8")

    def read_user(self) -> str:
        return self.user_path.read_text(encoding="utf-8")
