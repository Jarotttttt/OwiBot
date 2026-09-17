# OwiBot

Bot AI untuk kontrol workspace dan eksekusi task lewat Telegram. Menggunakan ReAct loop sederhana dengan tool-calling, memori persisten berbasis markdown, dan sistem skills.

## Kebutuhan

- Python 3.9+
- Token bot dari [@BotFather](https://t.me/BotFather)
- User ID Telegram dari [@userinfobot](https://t.me/userinfobot)
- Endpoint LLM (OpenAI, OpenRouter, Ollama, LM Studio, atau Codex CLI)

## Instalasi

```bash
git clone https://github.com/Jarotttttt/OwiBot.git
cd OwiBot
pip install -e .
```

## Setup

Jalankan wizard konfigurasi:

```bash
owibot setup
```

Atau setup langsung lewat flag tanpa prompt interaktif:

```bash
owibot setup \
  --api-base "http://localhost:20128/v1" \
  --api-key "local" \
  --model "ag/gemini-3.8-flash-low" \
  --token "TOKEN_BOT_TELEGRAM" \
  --allow "ID_TELEGRAM_KAMU" \
  --yes
```

Konfigurasi disimpan di `~/.owibot/config.json`.

## Menjalankan Bot

Jalankan gateway di background:

```bash
owibot gateway
```

Cek log jika diperlukan:

```bash
# Windows PowerShell
Get-Content ~/.owibot/gateway.log -Tail 20 -Wait

# Linux / macOS
tail -f ~/.owibot/gateway.log
```

Menghentikan gateway:

```bash
owibot gateway --stop
```

Menjalankan di foreground (terminal tetap menempel):

```bash
owibot gateway --fg
```

Autostart saat login Windows (tanpa perlu hak akses administrator):

```bash
owibot service install     # pasang shortcut di Startup
owibot service status      # cek status
owibot service uninstall   # copot autostart
```

Diagnosa konfigurasi dan environment:

```bash
owibot doctor
```

## Penggunaan di Telegram

Kirim pesan langsung ke bot. Semua eksekusi dibatasi hanya untuk user yang terdaftar di allowlist.

### Perintah Tersedia

- `/start` - Tampilkan panduan awal
- `/new` - Reset konteks percakapan aktif
- `/help` - Tampilkan daftar perintah

### Tools Bawaan

Model memiliki akses ke tools berikut di dalam direktori `~/.owibot/workspace`:

| Tool | Deskripsi |
|---|---|
| `read_file` | Membaca isi file |
| `write_file` | Menulis atau membuat file |
| `list_dir` | Melihat daftar file dan direktori |
| `exec` | Menjalankan perintah terminal (perintah berbahaya diblokir) |
| `web_fetch` | Mengambil konten teks dari URL |
| `update_memory` | Memperbarui catatan jangka panjang di `MEMORY.md` |
| `cron_job` | Menjadwalkan pengingat (`add`, `list`, `remove`) |

Semua operasi file dan eksekusi dibatasi pada folder workspace untuk mencegah akses ke luar direktori yang diizinkan.

### Format Config

File `~/.owibot/config.json`:

```json
{
  "api_base": "http://127.0.0.1:11434/v1",
  "model": "llama3.1",
  "api_key": "local",
  "channels": {
    "telegram": {
      "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
      "allow_from": ["123456789"]
    }
  }
}
```

## Struktur Proyek

```text
owibot/
├── agent/       # ReAct loop, tools, memory, skills
├── channels/    # Gateway Telegram (long-polling)
├── cli/         # Setup wizard, daemon manager, autostart service
├── prompts/     # Base instruction (AGENTS.md) dan MEMORY.md
├── provider/    # Client OpenAI-compatible dan Codex adapter
└── scheduler/   # Penyimpanan cron/reminder (cron.json)
```

## Lisensi

MIT
