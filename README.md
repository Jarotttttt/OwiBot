# OwiBot 🤖

> Lightweight personal AI assistant you control from Telegram. Chat, run tools, remember context, and schedule reminders — Hermes-style core in ~1k lines of Python.

[![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Telegram](https://img.shields.io/badge/control-Telegram-26A5E4)](https://core.telegram.org/bots)

OwiBot is a from-scratch personal AI agent: Hermes-style memory and skills core, single-channel Telegram control.

---

## Why OwiBot?

| | OwiBot | Full frameworks (Hermes / OpenClaw) |
|---|---|---|
| Size | ~1k lines core | Thousands–400k+ lines |
| Tools | 10 focused tools | 40–70+ tools |
| Control | Telegram only | 6–20+ platforms |
| Memory | Bounded Markdown + SQLite FTS5 | Same pattern, plus vector/user-modeling |
| Skills | Agent-managed `SKILL.md` + `/learn` | Plus hub, bundles, background review |
| Best for | Personal bot you can read in one sitting and hack in an afternoon | Autonomous fleets, multi-agent ops |

If you want a bot you fully understand and can shape feature-by-feature — start here.

## Features

- 🧠 **Any OpenAI-compatible LLM** — OpenAI, OpenRouter, Ollama, LM Studio, or Codex CLI. Switch by editing one config file.
- 💬 **Telegram gateway** — long-polling bot (no webhook needed), per-chat agent sessions, allowlist access control. Commands: `/new /model /retry /undo /compress /usage /sessions /memory /skills /learn /bg /stop /help`. Dangerous `exec`/`write_file` pause for inline ✅/❌ approval; `clarify` renders option buttons; voice memos transcribed when the provider allows.
- 🛠️ **14 sandboxed tools** — files, `exec`, `execute_code` (Python sandbox), `web_search` + `web_fetch`, `memory` (add/replace/remove), `skill_manage` + `skill_view`, `session_search`, `delegate_task` (subagents), `clarify`, `cron_job`. Workspace-jailed; destructive commands blocked.
- 🧾 **Persistent memory (Hermes-style)** — bounded `MEMORY.md` (2200 chars) + `USER.md` profile (1375 chars), curated via `add/replace/remove`, frozen snapshot per session, plus SQLite FTS5 `session_search` over all past chats.
- 🧩 **Skills (Hermes-style)** — OpenClaw-compatible `skills/*/SKILL.md`, progressive disclosure (`skill_view` loads full content on demand), agent-managed via `skill_manage` (`create/patch/edit/delete`). `/learn <name> | <material>` saves any workflow as a skill. Ships with `memory` + `cron` policies.
- ⏰ **Reminders** — one-time (`every_s=0`) or recurring (`every_s>0`), checked every 20s, delivered to the originating chat.

## Quick start

**Requirements:** Python ≥ 3.9, a Telegram bot token ([@BotFather](https://t.me/BotFather)), your Telegram user ID ([@userinfobot](https://t.me/userinfobot)).

```bash
pip install -e .
owibot setup      # guided wizard: provider → model (tested) → Telegram → protection
owibot gateway    # start the Telegram bot (Ctrl+C to stop)
owibot doctor     # diagnose this machine
```

The terminal is mission control only (setup, gateway, service, doctor) —
chatting happens in Telegram.

Autostart at Windows logon (no admin needed):

```bash
owibot service install     # Startup-folder entry
owibot service status      # check it
owibot service uninstall   # remove it
```

## Configuration

Config lives at `~/.owibot/config.json`, workspace at `~/.owibot/workspace`.

**OpenRouter (recommended — many cheap models):**

```json
{
  "api_base": "https://openrouter.ai/api/v1",
  "model": "z-ai/glm-4.5-air:free",
  "api_key": "sk-or-v1-YOUR_KEY",
  "memory": { "write_approval": false },
  "skills": { "write_approval": false },
  "channels": {
    "telegram": {
      "token": "YOUR_BOT_TOKEN",
      "allow_from": ["YOUR_TELEGRAM_ID"]
    }
  }
}
```

**Local, free via Ollama:**

```json
{
  "api_base": "http://127.0.0.1:11434/v1",
  "model": "llama3.1",
  "api_key": "local"
}
```

`allow_from` accepts user IDs, usernames (without `@`), or `"*"` (open — not recommended).

## How it works

```
Telegram / CLI
      │
      ▼
Agent.ask()  (owibot/agent/core.py)
  ├─ build system prompt: AGENTS.md + MEMORY.md + recalled history + always-skills + last 10 turns
  ├─ LLMProvider.chat()  (OpenAI-compatible POST / Codex CLI)
  ├─ while tool_calls and steps < 30: dispatch via LocalTools, feed results back
      ▼
reply + append turn to memory/history/*.jsonl
```

The Telegram gateway (`owibot/channels/telegram.py`) keeps one `Agent` per `chat_id`, shows a `typing…` indicator, splits replies over 3900 chars, and runs the cron loop that fires due jobs back to their chat.

## Tools reference

| Tool | What it does | Notes |
|---|---|---|
| `read_file` / `write_file` / `list_dir` | File ops inside workspace | Path escape rejected |
| `exec` | Run shell command in workspace | Timeout 1–120s, denylist enforced, approval for uncommon binaries |
| `execute_code` | Run a Python snippet (60s max) | Stdlib, temp file auto-cleaned |
| `web_search` | Free web search, no API key | DuckDuckGo, labeled untrusted |
| `delegate_task` | Subagent with own step budget | No nested delegation |
| `web_fetch` | Fetch URL as text | HTML stripped, labeled untrusted |
| `memory` | `add` / `replace` / `remove` curated facts | Targets `memory` / `user`, hard budgets |
| `clarify` | Ask user a question with options | Inline buttons in Telegram |
| `skill_manage` | `create` / `patch` / `edit` / `delete` / `list` skills | `patch` preferred for fixes |
| `skill_view` | Load full skill or one reference file | Progressive disclosure |
| `session_search` | FTS5 search over past chats | Per-chat or global |
| `cron_job` | `add` / `list` / `remove` reminders | `next_at` ISO datetime |

## Skills

Add a skill by creating `~/.owibot/workspace/skills/<name>/SKILL.md`:

```markdown
---
name: mystuff
description: When to use this skill.
always: true
---

Instructions injected into every prompt…
```

Omit `always` (or set `false`) to keep it dormant until the agent discovers it via the skill list.

## Project structure

```text
owibot/
├── agent/       # ReAct loop (core.py), tools.py, memory.py, skills.py
├── channels/    # Telegram gateway (telegram.py)
├── cli/         # onboard / gateway / chat entrypoints
├── provider/    # OpenAI-compatible + Codex CLI adapter
├── scheduler/   # cron.json store (cron.py)
├── skills/      # built-in SKILL.md (cron, memory)
└── prompts/     # AGENTS.md identity, MEMORY.md seed
```

## Security

- Telegram allowlist enforced before any reply (bot stays silent for strangers on `/start` except a pairing hint).
- All file/shell tools jailed to the workspace directory.
- Small denylist for destructive commands; `web_fetch` output is explicitly marked untrusted so the model won't treat pages as instructions.
- Never commit `~/.owibot/config.json` — it holds your API key + bot token.

## Roadmap

- [x] `/learn` — save a recurring pattern as a new `SKILL.md` from chat
- [x] Inline approval buttons for `exec` / `write_file`
- [x] Voice memo transcription (OpenAI audio endpoint; honest fallback otherwise)
- [x] `/bg` background sessions
- [x] Memory/skill write-approval staging (`/memory approve`, `/skills diff`)
- [x] Guided `owibot setup` wizard + autostart service

## Credits

Designed and built as OwiBot — a lightweight, hackable personal agent.

## License

MIT — see [LICENSE](LICENSE).
