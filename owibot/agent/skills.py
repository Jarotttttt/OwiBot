from __future__ import annotations

import re
from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

class SkillsLoader:
    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace_skills, self.builtin_skills = workspace / "skills", (builtin_skills_dir or BUILTIN_SKILLS_DIR)

    def list_skills(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []; seen: set[str] = set()
        for root in (self.workspace_skills, self.builtin_skills):
            if not root.exists(): continue
            for d in root.iterdir():
                if not d.is_dir() or d.name in seen: continue
                p = d / "SKILL.md"
                if p.exists(): out.append({"name": d.name, "path": str(p)}); seen.add(d.name)
        return out

    def load_skill(self, name: str) -> str | None:
        for root in (self.workspace_skills, self.builtin_skills):
            p = root / name / "SKILL.md"
            if p.exists(): return p.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, names: list[str]) -> str: return "\n\n---\n\n".join(f"### Skill: {n}\n\n{self._strip_frontmatter(c)}" for n in names if (c := self.load_skill(n)))

    def get_always_skills(self) -> list[str]:
        return [s["name"] for s in self.list_skills() if str((self.get_skill_metadata(s["name"]) or {}).get("always", "")).strip().lower() in {"1", "true", "yes", "on"}]

    def get_skill_metadata(self, name: str) -> dict | None:
        if not (c := self.load_skill(name)) or not (m := re.match(r"^---\n(.*?)\n---", c, re.DOTALL)): return None
        return {k.strip(): v.strip().strip('"\'') for line in m.group(1).split("\n") if ":" in line for k, v in [line.split(":", 1)]}

    @staticmethod
    def _strip_frontmatter(c: str) -> str:
        if c.startswith("---") and (m := re.match(r"^---\n.*?\n---\n?", c, re.DOTALL)): return c[m.end() :].strip()
        return c

    # -- progressive disclosure (Hermes pattern) --------------------------
    def index_text(self) -> str:
        """Level 0: name + description only. Full content loads via view()."""
        lines = []
        for s in self.list_skills():
            meta = self.get_skill_metadata(s["name"]) or {}
            lines.append(f"- {s['name']}: {str(meta.get('description', '')).strip() or 'no description'}")
        return "\n".join(lines)

    def view(self, name: str, rel_path: str = "") -> str:
        """Level 1/2: full SKILL.md, or one reference file inside the skill dir."""
        slug = self._valid_name(name)
        for root in (self.workspace_skills, self.builtin_skills):
            base = root / slug
            if not (base / "SKILL.md").exists():
                continue
            if not rel_path:
                return (base / "SKILL.md").read_text(encoding="utf-8")
            target = (base / rel_path).resolve()
            if base.resolve() not in target.parents or not target.is_file():
                raise ValueError("reference path escapes skill directory")
            return target.read_text(encoding="utf-8")[:12000]
        raise ValueError(f"skill not found: {name}")

    # -- agent-managed skills (skill_manage tool backend) -----------------
    @staticmethod
    def _valid_name(name: str) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
        if not slug:
            raise ValueError("skill name is empty")
        return slug[:64]

    @staticmethod
    def _lint(content: str) -> str:
        warns = []
        if not re.match(r"^---\n(.*?)\n---", content or "", re.DOTALL):
            warns.append("missing YAML frontmatter (--- name/description ---)")
        else:
            head = re.match(r"^---\n(.*?)\n---", content, re.DOTALL).group(1).lower()
            if "name:" not in head: warns.append("frontmatter missing 'name:'")
            if "description:" not in head: warns.append("frontmatter missing 'description:'")
        body = SkillsLoader._strip_frontmatter(content or "")
        if len(body) < 100: warns.append("body very short (<100 chars)")
        if len(content or "") > 12000: warns.append("skill very long (>12000 chars); split into references/")
        return (" warnings: " + "; ".join(warns)) if warns else ""

    def save_skill(self, name: str, content: str) -> str:
        """Create or overwrite a workspace skill with a full SKILL.md."""
        slug = self._valid_name(name)
        if not (content or "").strip():
            raise ValueError("content is empty (full SKILL.md required)")
        target = self.workspace_skills / slug / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.strip() + "\n", encoding="utf-8")
        return str(target) + self._lint(content)

    def patch_skill(self, name: str, old_string: str, new_string: str) -> str:
        slug = self._valid_name(name)
        target = self.workspace_skills / slug / "SKILL.md"
        if not target.exists():
            raise ValueError(f"workspace skill not found: {name} (patch only edits workspace skills)")
        current = target.read_text(encoding="utf-8")
        if not old_string or current.count(old_string) != 1:
            raise ValueError(f"old_string must match exactly once (found {current.count(old_string or '')})")
        target.write_text(current.replace(old_string, new_string or ""), encoding="utf-8")
        return str(target)

    def delete_skill(self, name: str) -> bool:
        slug = self._valid_name(name)
        target = self.workspace_skills / slug / "SKILL.md"
        if not target.exists():
            return False
        target.unlink()
        try:
            (self.workspace_skills / slug).rmdir()
        except OSError:
            pass
        return True
