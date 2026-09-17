from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_SKILLS_PATH = Path(__file__).resolve().parent.parent / "skills"


def sanitize_skill_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    if not slug:
        raise ValueError("Nama skill tidak boleh kosong.")
    return slug[:40]


class SkillsEngine:
    def __init__(self, workspace: Path, builtin_skills_path: Path | None = None):
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_path or DEFAULT_SKILLS_PATH
        self.workspace_skills.mkdir(parents=True, exist_ok=True)

    def list_skills(self) -> list[dict[str, str]]:
        skills_found: list[dict[str, str]] = []
        registered_names: set[str] = set()

        for directory in (self.workspace_skills, self.builtin_skills):
            if not directory.exists():
                continue
            for entry in directory.iterdir():
                if not entry.is_dir() or entry.name in registered_names:
                    continue
                skill_file = entry / "SKILL.md"
                if skill_file.is_file():
                    skills_found.append({
                        "name": entry.name,
                        "path": str(skill_file),
                    })
                    registered_names.add(entry.name)

        return skills_found

    def load_skill(self, name: str) -> str | None:
        clean_name = sanitize_skill_name(name)
        for directory in (self.workspace_skills, self.builtin_skills):
            target_file = directory / clean_name / "SKILL.md"
            if target_file.is_file():
                try:
                    return target_file.read_text(encoding="utf-8")
                except OSError:
                    return None
        return None

    def load_skill_reference(self, name: str, rel_path: str) -> str:
        """Level 2 progressive disclosure: membaca berkas referensi pendukung skill."""
        clean_name = sanitize_skill_name(name)
        for directory in (self.workspace_skills, self.builtin_skills):
            skill_dir = directory / clean_name
            if (skill_dir / "SKILL.md").is_file():
                target_file = (skill_dir / rel_path).resolve()
                if skill_dir.resolve() not in target_file.parents or not target_file.is_file():
                    raise ValueError("Akses di luar direktori skill ditolak.")
                try:
                    return target_file.read_text(encoding="utf-8")[:10000]
                except OSError as err:
                    raise RuntimeError(f"Gagal membaca referensi skill: {err}") from err
        raise ValueError(f"Skill '{name}' tidak ditemukan.")

    def load_skills_for_context(self, names: list[str]) -> str:
        blocks: list[str] = []
        for name in names:
            content = self.load_skill(name)
            if content:
                stripped = self._strip_frontmatter(content)
                blocks.append(f"### Skill: {name}\n\n{stripped}")
        return "\n\n---\n\n".join(blocks)

    def get_always_skills(self) -> list[str]:
        always_active: list[str] = []
        for skill in self.list_skills():
            metadata = self.get_skill_metadata(skill["name"]) or {}
            value = str(metadata.get("always", "")).strip().lower()
            if value in {"true", "1", "yes", "on"}:
                always_active.append(skill["name"])
        return always_active

    def get_skill_metadata(self, name: str) -> dict[str, str] | None:
        content = self.load_skill(name)
        if not content:
            return None

        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None

        metadata: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                metadata[key.strip()] = val.strip().strip('"\'')
        return metadata

    def index_summary(self) -> str:
        """Level 0 progressive disclosure: nama dan deskripsi ringkas saja."""
        lines = []
        for item in self.list_skills():
            meta = self.get_skill_metadata(item["name"]) or {}
            desc = meta.get("description", "").strip() or "Tanpa deskripsi"
            lines.append(f"- {item['name']}: {desc}")
        return "\n".join(lines)

    def save_skill(
        self,
        name: str,
        description: str,
        procedure: str,
        always: bool = False,
        pitfalls: str = "",
    ) -> str:
        clean_name = sanitize_skill_name(name)
        desc_clean = (description or "").strip() or f"Prosedur untuk {clean_name}"
        proc_clean = (procedure or "").strip()

        if not proc_clean:
            raise ValueError("Prosedur instruksi skill tidak boleh kosong.")

        sections = [
            "---",
            f"name: {clean_name}",
            f"description: {desc_clean[:80]}",
            f"always: {'true' if always else 'false'}",
            "---",
            "",
            f"# Skill: {clean_name}",
            "",
            "## Prosedur",
            proc_clean,
        ]
        if pitfalls.strip():
            sections.extend(["", "## Hal yang Perlu Dihindari", pitfalls.strip()])

        content = "\n".join(sections) + "\n"
        target_dir = self.workspace_skills / clean_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "SKILL.md"
        target_file.write_text(content, encoding="utf-8")

        return f"OK: Skill '{clean_name}' berhasil disimpan di {target_file}."

    def patch_skill(self, name: str, search_text: str, replacement_text: str) -> str:
        clean_name = sanitize_skill_name(name)
        target_file = self.workspace_skills / clean_name / "SKILL.md"
        if not target_file.is_file():
            raise ValueError(f"Skill workspace '{clean_name}' tidak ditemukan untuk dipatch.")

        content = target_file.read_text(encoding="utf-8")
        if not search_text or search_text not in content:
            raise ValueError(f"Teks target '{search_text[:40]}' tidak ditemukan dalam skill '{clean_name}'.")

        updated = content.replace(search_text, replacement_text, 1)
        target_file.write_text(updated, encoding="utf-8")
        return f"OK: Skill '{clean_name}' berhasil diperbarui."

    def delete_skill(self, name: str) -> bool:
        clean_name = sanitize_skill_name(name)
        target_dir = self.workspace_skills / clean_name
        target_file = target_dir / "SKILL.md"
        if not target_file.is_file():
            return False

        target_file.unlink()
        try:
            target_dir.rmdir()
        except OSError:
            pass
        return True

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n?", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content.strip()


# Backward-compatible alias
SkillsLoader = SkillsEngine
