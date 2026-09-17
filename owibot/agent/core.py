from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .lifecycle import AgentLifecycleEngine, AgentPhase
from .memory import MemoryStore
from .skills import SkillsEngine
from .tools import TOOLS, LocalTools
from ..mcp import MCPManager
from ..observability import AgentTracer
from ..provider.base import LLMResponse, TokenUsage
from ..provider.provider import LLMProvider

BASE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "AGENTS.md"
MAX_DELEGATION_DEPTH = 1


def _read_prompt_instructions(primary_path: Path, fallback_path: Path) -> str:
    for path in (primary_path, fallback_path):
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            continue
    raise RuntimeError(f"File prompt dasar tidak ditemukan di {primary_path} maupun {fallback_path}")


def format_tool_progress(name: str, args: dict) -> str:
    if name == "exec":
        cmd = str(args.get("command", "")).strip()
        return f"⚡ Menjalankan: `{cmd[:45]}`"
    if name == "read_file":
        path = str(args.get("path", "")).strip()
        return f"📖 Membaca file: `{path}`"
    if name == "write_file":
        path = str(args.get("path", "")).strip()
        return f"✍️ Menulis file: `{path}`"
    if name == "web_fetch":
        url = str(args.get("url", "")).strip()
        return f"🌐 Mengunduh: `{url[:45]}`"
    if name == "list_dir":
        path = str(args.get("path", ".")).strip()
        return f"📁 Melihat folder: `{path}`"
    if name == "update_memory":
        return "🧠 Memperbarui memori..."
    if name == "session_search":
        q = str(args.get("query", "")).strip()
        return f"🔍 Mencari sesi lalu: `{q[:35]}`"
    if name == "skill_view":
        sname = str(args.get("name", "")).strip()
        return f"📚 Membaca skill: `{sname}`"
    if name == "skill_manage":
        act = str(args.get("action", "")).strip()
        return f"🛠️ Mengelola skill ({act})..."
    if name == "delegate_task":
        task = str(args.get("task", "")).strip()
        return f"👥 Mendelegasikan ke subagent: `{task[:35]}`"
    if name == "cron_job":
        return "⏰ Mengatur pengingat..."
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        srv = parts[1] if len(parts) > 1 else "mcp"
        tname = parts[2] if len(parts) > 2 else name
        return f"🔌 MCP ({srv}): `{tname}`"
    return f"⚙️ Menjalankan tool: `{name}`"


class Agent:
    def __init__(
        self,
        workspace: Path,
        llm: LLMProvider,
        chat_id: str = "default",
        depth: int = 0,
        mcp_manager: MCPManager | None = None,
        tracer: AgentTracer | None = None,
    ):
        self.workspace = workspace
        self.llm = llm
        self.chat_id = chat_id
        self.depth = depth
        self.mcp_manager = mcp_manager
        self.tracer = tracer or AgentTracer(chat_id=chat_id)

        self.memory = MemoryStore(workspace)
        self.skills = SkillsEngine(workspace)
        self.tools = LocalTools(workspace)
        self.tools.set_subagent_runner(self._spawn_subagent)
        self.lifecycle = AgentLifecycleEngine(self)

        self.workspace_prompt_file = (workspace / "AGENTS.md").resolve()
        self.recent_history: list[dict] = []
        self.max_steps: int = 30
        self.last_plan: list[Any] = []
        self.last_lifecycle_state: Any = None

        skill_entries: list[str] = []
        for item in self.skills.list_skills():
            meta = self.skills.get_skill_metadata(item["name"]) or {}
            desc = meta.get("description", "").strip() or "Tidak ada deskripsi"
            skill_entries.append(f"{item['name']}: {desc}")

        self.available_skills_summary = "; ".join(skill_entries)
        self.always_active_skills = self.skills.load_skills_for_context(self.skills.get_always_skills())

    def _spawn_subagent(self, task_description: str, budget: int = 5) -> str:
        if self.depth >= MAX_DELEGATION_DEPTH:
            return "ERROR: Delegasi subagent bersarang dilarang (maksimum kedalaman tercapai)."

        subagent = Agent(
            workspace=self.workspace,
            llm=self.llm,
            chat_id=f"{self.chat_id}:subagent",
            depth=self.depth + 1,
            mcp_manager=self.mcp_manager,
            tracer=self.tracer,
        )
        subagent.max_steps = max(2, min(budget, 8))
        return subagent.ask(task_description)

    def get_available_tools(self) -> list[dict]:
        tools_catalog = list(TOOLS)
        if self.mcp_manager:
            tools_catalog.extend(self.mcp_manager.cached_tools)
        return tools_catalog

    def dispatch_tool(self, name: str, arguments: dict) -> str:
        if self.mcp_manager and self.mcp_manager.is_mcp_tool(name):
            return self.mcp_manager.dispatch(name, arguments)
        return self.tools.dispatch(name, arguments)

    def _assemble_prompt(self, user_message: str, timestamp_iso: str = "") -> list[dict]:
        sections: list[str] = [
            _read_prompt_instructions(self.workspace_prompt_file, BASE_PROMPT_PATH),
            "## Berkas Memori\n- Memori utama: memory/MEMORY.md\n- Profil pengguna: memory/USER.md\n- Log percakapan: memory/history/YYYY-MM-DD.jsonl",
        ]

        if self.always_active_skills:
            sections.append(f"## Skills Aktif\n{self.always_active_skills}")

        user_profile = self.memory.read_user_profile().strip()
        if user_profile:
            sections.append(f"## Profil Pengguna\n{user_profile}")

        saved_memory = self.memory.read_memory().strip()
        if saved_memory:
            sections.append(f"## Catatan Memori\n{saved_memory}")

        relevant_history = self.memory.search_history(user_message, limit=5, chat_id=self.chat_id)
        if relevant_history:
            sections.append("## Riwayat Percakapan Relevan\n" + "\n\n".join(relevant_history))

        system_instruction = "\n\n---\n\n".join(sections)
        if self.available_skills_summary:
            system_instruction += f"\n\n## Skills yang Tersedia (Gunakan tool skill_view untuk melihat)\n- {self.available_skills_summary}"
        if timestamp_iso:
            system_instruction += f"\n\n## Waktu Sistem\n- created_at: {timestamp_iso}"

        messages = [{"role": "system", "content": system_instruction}]
        messages.extend(self.recent_history[-10:])
        messages.append({"role": "user", "content": user_message})
        return messages

    def format_tool_progress(self, name: str, args: dict) -> str:
        return format_tool_progress(name, args)

    def ask(self, user_message: str, context: dict | None = None) -> str:
        return self.lifecycle.run(user_message, context=context)
