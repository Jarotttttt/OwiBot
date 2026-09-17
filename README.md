# OwiBot 🤖

> Asisten AI pribadi yang kamu kendalikan dari Telegram. Chat, jalankan tools, ingat konteks, dan jadwalkan pengingat — inti gaya Hermes dalam ~1k baris Python.

[![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Telegram](https://img.shields.io/badge/control-Telegram-26A5E4)](https://core.telegram.org/bots)

OwiBot adalah AI agent buatan sendiri dari nol: inti memory dan skills ala Hermes, kontrol satu pintu via Telegram.

---

## Kenapa OwiBot?

| | OwiBot | Framework besar (Hermes / OpenClaw) |
|---|---|---|
| Ukuran | inti ~1k baris | ribuan–400k+ baris |
| Tools | 14 yang fokus | 40–70+ tools |
| Kontrol | Telegram saja | 6–20+ platform |
| Memory | Markdown berbatas + SQLite FTS5 | pola sama, plus vector/user-modeling |
| Skills | `SKILL.md` dikelola agent + `/learn` | plus hub, bundles, background review |
| Cocok untuk | bot pribadi yang isinya kamu paham luar-dalam dan gampang dioprek | armada multi-agent, operasi tim |

Kalau mau bot yang kamu mengerti sepenuhnya dan bisa dibentuk fitur per fitur — mulai dari sini.

## Fitur

- 🧠 **LLM OpenAI-compatible apa saja** — OpenAI, OpenRouter, Ollama, LM Studio, atau Codex CLI. Ganti cukup edit satu file config.
- 💬 **Gateway Telegram** — bot long-polling (tanpa webhook), satu session agent per chat, allowlist akses. Perintah: `/new /model /retry /undo /compress /usage /sessions /memory /skills /learn /bg /stop /help`. `exec`/`write_file` berbahaya berhenti minta persetujuan tombol ✅/❌; `clarify` tampil sebagai tombol pilihan; voice memo ditranskrip kalau provider mendukung.
- 🛠️ **14 tools tersandbox** — file, `exec`, `execute_code` (sandbox Python), `web_search` + `web_fetch`, `memory` (add/replace/remove), `skill_manage` + `skill_view`, `session_search`, `delegate_task` (subagent), `clarify`, `cron_job`. Semua dikurung di workspace; perintah destruktif diblokir.
- 🧾 **Memory persisten ala Hermes** — `MEMORY.md` berbatas (2200 char) + profil `USER.md` (1375 char), dikurasi via `add/replace/remove`, snapshot beku per session, plus `session_search` SQLite FTS5 ke semua chat lama.
- 🧩 **Skills ala Hermes** — `skills/*/SKILL.md` format OpenClaw, progressive disclosure (`skill_view` muat isi penuh hanya saat perlu), dikelola agent via `skill_manage` (`create/patch/edit/delete`). `/learn <nama> | <materi>` menyimpan workflow apa pun jadi skill. Bawaan: kebijakan `memory` + `cron`.
- ⏰ **Pengingat** — sekali (`every_s=0`) atau berulang (`every_s>0`), dicek tiap 20 detik, dikirim ke chat asal.

## Mulai cepat

**Syarat:** Python ≥ 3.9, token bot Telegram ([@BotFather](https://t.me/BotFather)), ID Telegram kamu ([@userinfobot](https://t.me/userinfobot)).

```bash
pip install -e .
owibot setup      # wizard: provider → model (dites) → Telegram → proteksi
owibot gateway    # bot langsung jalan di background
owibot gateway --stop   # matikan bot background
owibot doctor     # diagnosa mesin ini
```

Terminal hanya mission control (setup, gateway, service, doctor) —
ngobrolnya di Telegram.

Jalan otomatis tiap logon Windows (tanpa admin):

```bash
owibot service install     # entri Startup-folder
owibot service status      # cek status
owibot service uninstall   # hapus
```

Setup non-interaktif (tanpa menu ketik):

```bash
owibot setup --api-base URL --api-key KEY --model MODEL --token TOK --allow ID --yes
```

## Konfigurasi

Config di `~/.owibot/config.json`, workspace di `~/.owibot/workspace`.

**OpenRouter (rekomendasi — banyak model murah):**

```json
{
  "api_base": "https://openrouter.ai/api/v1",
  "model": "z-ai/glm-4.5-air:free",
  "api_key": "sk-or-v1-KUNCI_KAMU",
  "memory": { "write_approval": false },
  "skills": { "write_approval": false },
  "channels": {
    "telegram": {
      "token": "TOKEN_BOT_KAMU",
      "allow_from": ["ID_TELEGRAM_KAMU"]
    }
  }
}
```

**Lokal, gratis via Ollama:**

```json
{
  "api_base": "http://127.0.0.1:11434/v1",
  "model": "llama3.1",
  "api_key": "local"
}
```

`allow_from` menerima ID user, username (tanpa `@`), atau `"*"` (terbuka — tidak disarankan).

## Cara kerja

```
Telegram
   │
   ▼
Agent.ask()  (owibot/agent/core.py)
  ├─ susun system prompt: AGENTS.md + MEMORY.md + riwayat relevan + always-skills + 10 turn terakhir
  ├─ LLMProvider.chat()  (POST OpenAI-compatible / Codex CLI)
  ├─ selama ada tool_calls dan langkah < 30: dispatch via LocalTools, hasilnya dibalikkan lagi
   ▼
balasan + turn disimpan ke memory/history/*.jsonl
```

Gateway Telegram (`owibot/channels/telegram.py`) menyimpan satu `Agent` per `chat_id`, menampilkan indikator `typing…`, memecah balasan >3900 char, dan menjalankan loop cron yang menembak job jatuh tempo ke chat asalnya.

## Referensi tools

| Tool | Fungsinya | Catatan |
|---|---|---|
| `read_file` / `write_file` / `list_dir` | Operasi file di workspace | Path escape ditolak |
| `exec` | Perintah shell di workspace | Timeout 1–120 dtk, denylist + approval untuk binary tak umum |
| `execute_code` | Snippet Python (maks 60 dtk) | Stdlib, file temp auto-hapus |
| `web_search` | Search web gratis, tanpa API key | DuckDuckGo, dilabel untrusted |
| `delegate_task` | Subagent dengan budget langkah sendiri | Tanpa delegasi bersarang |
| `web_fetch` | Ambil URL sebagai teks | HTML dibersihkan, dilabel untrusted |
| `memory` | Fakta kurasi `add` / `replace` / `remove` | Target `memory` / `user`, budget keras |
| `clarify` | Tanya user dengan opsi | Tombol inline di Telegram |
| `skill_manage` | `create` / `patch` / `edit` / `delete` / `list` skills | `patch` diutamakan untuk perbaikan |
| `skill_view` | Muat skill penuh atau satu file referensi | Progressive disclosure |
| `session_search` | Cari FTS5 ke chat-chat lama | Per-chat atau global |
| `cron_job` | Pengingat `add` / `list` / `remove` | `next_at` datetime ISO |

## Skills

Tambah skill dengan membuat `~/.owibot/workspace/skills/<nama>/SKILL.md`:

```markdown
---
name: mystuff
description: Kapan skill ini dipakai.
always: true
---
```

Hilangkan `always` (atau `false`) agar dorman sampai agent menemukannya via daftar skill.

## Struktur proyek

```text
owibot/
├── agent/       # loop ReAct (core.py), tools.py, memory.py, skills.py, staging.py
├── channels/    # gateway Telegram (telegram.py) + voice.py
├── cli/         # setup / gateway / service / doctor (ui.py, daemon.py)
├── provider/    # adapter OpenAI-compatible + Codex CLI
├── scheduler/   # penyimpanan cron.json (cron.py)
├── skills/      # SKILL.md bawaan (cron, memory)
└── prompts/     # identitas AGENTS.md, seed MEMORY.md + USER.md
```

## Keamanan

- Allowlist Telegram ditegakkan sebelum balasan apa pun (bot diam ke orang asing, kecuali petunjuk pairing di `/start`).
- Semua tools file/shell dikurung di direktori workspace.
- Denylist kecil untuk perintah destruktif; output `web_fetch` ditandai untrusted agar model tidak memperlakukan halaman web sebagai instruksi.
- Jangan pernah commit `~/.owibot/config.json` — isinya API key + token bot.

## Roadmap

- [x] `/learn` — simpan pola berulang jadi `SKILL.md` baru dari chat
- [x] Tombol approval inline untuk `exec` / `write_file`
- [x] Transkripsi voice memo (endpoint audio OpenAI; fallback jujur bila tak bisa)
- [x] Session background `/bg`
- [x] Staging persetujuan tulis memory/skill (`/memory approve`, `/skills diff`)
- [x] Wizard `owibot setup` terpandu + service autostart + gateway background

## Kredit

Dirancang dan dibangun sebagai OwiBot — agent pribadi yang ringan dan gampang dioprek.

## Lisensi

MIT — lihat [LICENSE](LICENSE).
