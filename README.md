# OwiBot 🤖

> Asisten AI pribadi yang kamu kendalikan dari Telegram. Chat, jalankan tools, ingat konteks, dan jadwalkan pengingat — ringan, satu paket Python.

[![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Telegram](https://img.shields.io/badge/control-Telegram-26A5E4)](https://core.telegram.org/bots)

OwiBot adalah AI agent pribadi: inti kecil yang gampang dipahami dan dioprek, kontrol satu pintu via Telegram.

## Fitur

- 🧠 **Banyak provider LLM** — endpoint OpenAI-compatible (OpenAI, OpenRouter, Ollama, LM Studio) dan mode Codex CLI.
- 💬 **Gateway Telegram** — bot long-polling (tanpa webhook), satu session agent per chat, allowlist akses (`/start` `/new` `/help`).
- 🧾 **Memory persisten** — `MEMORY.md` jangka panjang + log harian yang bisa dicari.
- ⏰ **Pengingat terjadwal** — sekali atau berulang, dikirim ke chat asal.
- 🧩 **Skills** — format `SKILL.md` ala OpenClaw. Bawaan: kebijakan `memory` + `cron`.
- 🚀 **Setup terpandu** — wizard interaktif + mode flags non-interaktif, koneksi dites sebelum disimpan.

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

**OpenRouter (banyak model murah):**

```json
{
  "api_base": "https://openrouter.ai/api/v1",
  "model": "z-ai/glm-4.5-air:free",
  "api_key": "sk-or-v1-KUNCI_KAMU",
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
Pesan Telegram
     │
     ▼
Agent.ask()  (owibot/agent/core.py)
  ├─ susun system prompt + memory + riwayat relevan + skills
  ├─ panggil LLM (POST OpenAI-compatible / Codex CLI)
  ├─ kalau ada tool_calls: eksekusi, hasilnya dibalikkan, ulangi (maks 30 langkah)
     ▼
balasan dikirim ke chat + turn disimpan ke history
```

## Tools bawaan

| Tool | Fungsinya |
|---|---|
| `read_file` / `write_file` / `list_dir` | Operasi file di workspace |
| `exec` | Perintah shell di workspace (blokir perintah berbahaya) |
| `web_fetch` | Ambil URL sebagai teks |
| `update_memory` | Ganti isi `MEMORY.md` |
| `cron_job` | Pengingat `add` / `list` / `remove` |

## Struktur proyek

```text
owibot/
├── agent/       # loop agent (core.py), tools.py, memory.py, skills.py
├── channels/    # gateway Telegram (telegram.py)
├── cli/         # setup / gateway / service / doctor (ui.py, daemon.py)
├── provider/    # adapter OpenAI-compatible + Codex CLI
├── scheduler/   # penyimpanan cron.json (cron.py)
├── skills/      # SKILL.md bawaan (cron, memory)
└── prompts/     # identitas AGENTS.md, seed MEMORY.md
```

## Keamanan

- Allowlist Telegram ditegakkan sebelum balasan apa pun.
- Semua tools file/shell dikurung di direktori workspace, perintah berbahaya diblokir.
- Jangan pernah commit `~/.owibot/config.json` — isinya API key + token bot.

## Kredit

Dirancang dan dibangun sebagai OwiBot — agent pribadi yang ringan dan gampang dioprek.

## Lisensi

MIT — lihat [LICENSE](LICENSE).
