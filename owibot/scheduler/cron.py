from __future__ import annotations

import json
import time
from pathlib import Path


class CronStore:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.jobs: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.file_path.exists():
            self.jobs = []
            return
        try:
            content = self.file_path.read_text(encoding="utf-8")
            data = json.loads(content)
            self.jobs = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            self.jobs = []

    def _save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(self.jobs, ensure_ascii=False, indent=2) + "\n"
        self.file_path.write_text(serialized, encoding="utf-8")

    def add(self, chat_id: str, prompt: str, next_at: int, every_s: int = 0) -> str:
        self._load()
        existing_ids = [
            int(job["id"])
            for job in self.jobs
            if str(job.get("id", "")).isdigit()
        ]
        new_id = str(max(existing_ids + [0]) + 1)

        job_entry = {
            "id": new_id,
            "chat_id": str(chat_id),
            "prompt": prompt.strip(),
            "next_at": int(next_at),
            "every_s": max(0, int(every_s or 0)),
            "enabled": True,
            "created_at": int(time.time()),
        }
        self.jobs.append(job_entry)
        self._save()
        return new_id

    def list_for(self, chat_id: str | None = None) -> list[dict]:
        self._load()
        if chat_id is None:
            return list(self.jobs)
        return [job for job in self.jobs if str(job.get("chat_id")) == str(chat_id)]

    def remove(self, chat_id: str | None, job_id: str) -> bool:
        self._load()
        target_id = str(job_id).strip()
        initial_count = len(self.jobs)

        if chat_id is None:
            self.jobs = [job for job in self.jobs if str(job.get("id")) != target_id]
        else:
            self.jobs = [
                job for job in self.jobs
                if not (str(job.get("chat_id")) == str(chat_id) and str(job.get("id")) == target_id)
            ]

        has_changed = len(self.jobs) != initial_count
        if has_changed:
            self._save()
        return has_changed

    def due(self, now: int | None = None) -> list[dict]:
        self._load()
        current_time = int(time.time()) if now is None else int(now)
        return [
            job for job in self.jobs
            if job.get("enabled", True) and int(job.get("next_at", 0) or 0) <= current_time
        ]

    def mark_ran(self, job_id: str, now: int | None = None) -> bool:
        self._load()
        current_time = int(time.time()) if now is None else int(now)
        target_id = str(job_id)

        for job in self.jobs:
            if str(job.get("id")) != target_id:
                continue

            interval = int(job.get("every_s", 0) or 0)
            if interval > 0:
                job["next_at"] = current_time + interval
            else:
                job["enabled"] = False

            self._save()
            return True

        return False
