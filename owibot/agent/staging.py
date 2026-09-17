"""Staged writes (Hermes-style write_approval gate).

When the gate is on, agent memory/skill writes are stored here instead of
applied. They survive restarts and are reviewed with /memory and /skills.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class StagedStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]\n", encoding="utf-8")

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def add(self, kind: str, op: dict, gist: str) -> str:
        items = self._load()
        nid = str(max([int(i.get("id", 0)) for i in items if str(i.get("id", "")).isdigit()] + [0]) + 1)
        items.append({"id": nid, "kind": kind, "op": op, "gist": gist[:200],
                      "ts": int(time.time())})
        self._save(items)
        return nid

    def list(self) -> list[dict]:
        return self._load()

    def pop(self, nid: str) -> dict | None:
        items = self._load()
        for i, item in enumerate(items):
            if str(item.get("id")) == str(nid).strip():
                return self._save(items[:i] + items[i + 1:]) or item
        return None

    def pop_all(self) -> list[dict]:
        items = self._load()
        self._save([])
        return items
