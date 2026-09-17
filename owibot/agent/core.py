"""OwiBot agent loop (Hermes Fase 1): tiered prompt, frozen memory snapshot, session ops."""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from .memory import MemoryStore
from .skills import SkillsLoader
from .tools import TOOLS, PENDING_PREFIX, LocalTools
from ..provider.provider import LLMProvider

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "AGENTS.md"


def _load_rules(primary: Path, fallback: Path) -> str:
    for p in (primary, fallback):
        try: text = p.read_text(encoding="utf-8").strip()
        except OSError: continue
        if text: return text
    raise RuntimeError(f"Missing or unreadable prompt file: {primary} (fallback: {fallback})")


class Agent:
    def __init__(self, workspace: Path, llm: LLMProvider, chat_id: str = "default"):
        self.workspace, self.llm, self.chat_id = workspace, llm, chat_id
        self.memory, self.skills = MemoryStore(workspace), SkillsLoader(workspace)
        self.tools = LocalTools(workspace)
        self.tools._memory = self.memory
        self.workspace_prompt_path = (workspace / "AGENTS.md").resolve()
        self.recent: list[dict] = []; self.max_steps = 30
        self.last_user = ""
        self.session_tool_calls = 0
        self.pending: dict[str, dict] = {}
        self.tools.set_delegate_factory(self._run_subagent)
        self.freeze_snapshot()

    # -- prompt tiers (stable / context-frozen / volatile) ----------------
    def freeze_snapshot(self) -> None:
        """Capture memory + skill index once per session (Hermes frozen pattern)."""
        self._stable = _load_rules(self.workspace_prompt_path, PROMPT_PATH)
        self._skill_index = self.skills.index_text()
        self._always = self.skills.load_skills_for_context(self.skills.get_always_skills())
        self._snapshot = self.memory.snapshot()

    def _build_messages(self, user_text: str, created_at_iso: str = "") -> list[dict]:
        parts = [self._stable]
        if self._skill_index:
            parts.append("## Skills index (use skill_view to load one)\n" + self._skill_index)
        if self._always:
            parts.append("## Always-loaded skills\n" + self._always)
        parts.append(self._snapshot)
        system = "\n\n---\n\n".join(parts)
        if created_at_iso:
            system += f"\n\n## Runtime\n- created_at_iso: {created_at_iso}"
        return [{"role": "system", "content": system}, *self.recent[-10:], {"role": "user", "content": user_text}]

    def ask(self, user_text: str, context: dict | None = None) -> str:
        created_at_iso = datetime.now().astimezone().replace(microsecond=0).isoformat()
        tool_ctx = {**(context or {}), "created_at_iso": created_at_iso,
                    "chat_id": self.chat_id}
        is_cron = bool(tool_ctx.get("is_cron"))
        self.tools.set_context(tool_ctx)
        self.pending = {}
        prompt = (f"[Scheduled Task] Timer finished.\nInstruction: {user_text.strip()}."
                  if is_cron else user_text)
        messages = self._build_messages(prompt, created_at_iso=created_at_iso)
        return self._run(messages, self.max_steps, top_level=True, user_text=user_text,
                         is_cron=is_cron)

    def _run(self, messages: list[dict], steps_left: int, top_level: bool,
             user_text: str, is_cron: bool) -> str:
        from .tools import parse_pending_marker
        final, calls = "", 0
        while steps_left > 0:
            steps_left -= 1
            resp = self.llm.chat(messages, tools=TOOLS)
            if not resp["tool_calls"]:
                final = (resp["text"] or "").strip() or "(empty response)"
                messages.append({"role": "assistant", "content": final}); break
            calls += len(resp["tool_calls"])
            messages.append({"role": "assistant", "content": resp["text"] or "", "tool_calls": [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}} for tc in resp["tool_calls"]]})
            paused = None
            for tc in resp["tool_calls"]:
                result = self.tools.dispatch(tc["name"], tc["arguments"])[:5000]
                if pid := parse_pending_marker(result):
                    op = self.tools.pending_ops.pop(pid, None)
                    if op is None:
                        result = "ERROR: approval state lost; retry the action"
                    else:
                        self.pending[pid] = {"messages": messages, "tc": tc,
                                             "steps_left": steps_left, "op": op,
                                             "top_level": top_level, "user_text": user_text,
                                             "is_cron": is_cron, "calls": calls}
                        messages.append({"role": "tool", "tool_call_id": tc["id"],
                                         "name": tc["name"], "content": "AWAITING_USER_DECISION"})
                        paused = result
                        break
                messages.append({"role": "tool", "tool_call_id": tc["id"], "name": tc["name"], "content": result})
            if paused:
                return paused

        if not final: final = "I couldn't finish this in one pass (too many tool steps). Please try again with a more specific request."
        return self._finish(final, calls, top_level, user_text, is_cron)

    def _finish(self, final: str, calls: int, top_level: bool,
                user_text: str, is_cron: bool) -> str:
        self.session_tool_calls += calls
        if top_level:
            self.last_user = user_text
            self.recent = [*self.recent, {"role": "user", "content": user_text},
                           {"role": "assistant", "content": final}][-10:]
            self.memory.append_turn(user_text, final, self.chat_id)
            if calls >= 5 and not is_cron:
                final += ("\n\nTIP: this took several tool steps. Reply `/learn <name>` and I will "
                          "save the workflow as a reusable skill.")
        return final

    # -- approval + clarify resume --------------------------------------
    def _resume(self, pid: str, tool_result: str) -> str:
        entry = self.pending.pop(pid, None)
        if entry is None:
            return "ERROR: no such pending request (it may have expired)."
        tc = entry["tc"]
        entry["messages"][:] = [m for m in entry["messages"]
                                if not (m.get("role") == "tool" and m.get("tool_call_id") == tc["id"]
                                        and m.get("content") == "AWAITING_USER_DECISION")]
        entry["messages"].append({"role": "tool", "tool_call_id": tc["id"],
                                  "name": tc["name"], "content": tool_result[:5000]})
        out = self._run(entry["messages"], entry["steps_left"], top_level=entry["top_level"],
                        user_text=entry["user_text"], is_cron=entry["is_cron"])
        self.session_tool_calls += entry["calls"]
        return out

    def approve(self, pid: str) -> str:
        entry = self.pending.get(pid)
        if entry is None or entry["op"].get("kind") != "approve":
            return "ERROR: no such approval request."
        op = entry["op"]
        return self._resume(pid, self.tools.dispatch(op["tool"], op["args"], force=True))

    def deny(self, pid: str) -> str:
        entry = self.pending.get(pid)
        if entry is None or entry["op"].get("kind") != "approve":
            return "ERROR: no such approval request."
        return self._resume(pid, "Denied by the user. Do the task another way or propose alternatives.")

    def answer_clarify(self, pid: str, answer: str) -> str:
        entry = self.pending.get(pid)
        if entry is None or entry["op"].get("kind") != "clarify":
            return "ERROR: no such clarify request."
        answer = (answer or "").strip() or "(no answer given)"
        return self._resume(pid, f"User's answer: {answer}")

    def _run_subagent(self, task: str, budget: int) -> str:
        child = Agent(workspace=self.workspace, llm=self.llm,
                      chat_id=f"{self.chat_id}:sub")
        child.max_steps = budget
        return child.ask(task, {"chat_id": child.chat_id, "subagent": True})

    # -- session ops (/new /retry /undo /compress /usage /model) ----------
    def reset(self) -> str:
        self.recent = []; self.last_user = ""; self.pending = {}; self.freeze_snapshot()
        return "Started a new conversation (memory snapshot reloaded)."

    def retry(self) -> str:
        if not self.last_user:
            return "Nothing to retry yet."
        self.recent = self.recent[:-2] if len(self.recent) >= 2 else []
        return self.ask(self.last_user)

    def undo(self) -> str:
        if len(self.recent) < 2:
            return "Nothing to undo."
        self.recent = self.recent[:-2]
        self.last_user = next(
            (m["content"] for m in reversed(self.recent) if m["role"] == "user"), "")
        return "Removed the last exchange."

    def compress(self) -> str:
        if not self.recent:
            return "Nothing to compress."
        lines = []
        for m in self.recent:
            role = "USER" if m["role"] == "user" else "BOT"
            text = str(m.get("content", "")).replace("\n", " ").strip()[:200]
            if text: lines.append(f"- {role}: {text}")
        summary = ("# Last compressed summary (%s)\n\n" % datetime.now().strftime("%Y-%m-%d %H:%M")
                   + "\n".join(lines) + "\n")
        (self.workspace / "memory" / "last_summary.md").write_text(summary, encoding="utf-8")
        self.recent = []
        return f"Context compressed ({len(lines)} turns summarized to memory/last_summary.md)."

    def usage(self) -> str:
        st = self.memory.stats(self.chat_id)
        return (f"Session {self.chat_id}: {len(self.recent) // 2} live exchanges, "
                f"{self.session_tool_calls} tool calls this process. "
                f"History: {st['turns']} turns / ~{st['chars']} chars. "
                f"Memory budget: {st['memory']}. User profile: {st['user']}.")

    def set_model(self, model: str) -> str:
        model = (model or "").strip()
        if not model:
            return f"Current model: {self.llm.model}"
        self.llm.model = model
        self.memory.save_meta(self.chat_id, "model", model)
        return f"Model switched to {model} for this chat."

    @staticmethod
    def learn_prompt(name: str, material: str) -> str:
        return (
            f"/learn task: create a reusable skill named '{name.strip()}' from this material. "
            "Follow the house format: SKILL.md with --- name/description --- frontmatter "
            "(description max 60 chars), sections When to Use / Procedure / Pitfalls / Verification. "
            "Capture lessons and decision rules, not chat logs. Save it with skill_manage action=create, "
            "then reply with a one-line summary of what was saved.\n\nMaterial:\n" + (material or "").strip()
        )
