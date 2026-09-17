# OwiBot

Ekosistem Autonomous AI Agent modular untuk kontrol workspace, otomasi tugas, dan eksekusi coding melalui Telegram. Menggunakan arsitektur agen berbasis lifecycle (understand, plan, execute, verify, recover, finalize), memori dua lapis (curated notes dan SQLite FTS5 session search), skills dengan progressive disclosure, delegasi subagent terisolasi, integrasi protokol MCP (Model Context Protocol), keamanan berlapis, serta penelusuran audit otomatis.

## Arsitektur & Siklus Agen

Setiap permintaan pengguna diproses melalui 6 fase lifecycle terkontrol:

1. **Understand**: Memeriksa konteks instruksi, memori jangka panjang, profil pengguna, dan riwayat obrolan relevan.
2. **Plan**: Menyusun strategi eksekusi untuk tugas multi-langkah sebelum mengeksekusi aksi.
3. **Execute**: Memanggil tools lokal, subagent, atau tool eksternal dari server MCP.
4. **Verify**: Mengevaluasi luaran tool secara deterministik (memeriksa kode keluar, error runtime, atau file hasil).
5. **Recover**: Menyuntikkan panduan perbaikan mandiri (*self-verification nudge*) dan mencoba strategi alternatif jika eksekusi tool mengalami kendala (dibatasi hingga 3 percobaan).
6. **Finalize**: Menyimpan percakapan ke riwayat FTS5, mencatat telemetri latensi/token, dan mengirimkan ringkasan hasil ke Telegram.

## Komponen Sistem

- **Layered Memory**:
  - *Lapis 1 (Curated Long-Term)*: `MEMORY.md` (aturan & catatan lingkungan) dan `USER.md` (profil pengguna) dengan batas karakter dan perlindungan deduplikasi.
  - *Lapis 2 (Session Search)*: Indeks pencarian teks penuh SQLite FTS5 (BM25 ranking) untuk mencari riwayat percakapan lampau lintas tanggal via `session_search`.
- **Skills Engine (Progressive Disclosure)**:
  - *Level 0*: Ringkasan nama dan deskripsi di system prompt untuk menghemat token.
  - *Level 1*: Konten instruksi `SKILL.md` lengkap dibuka on-demand via `skill_view`.
  - *Level 2*: Dokumen dan berkas referensi pendukung di folder `references/`.
  - *Manajemen Mandiri*: Agent dapat membuat, memperbarui (*patch*), atau menghapus skill via `skill_manage`.
- **Controlled Subagents**: Tool `delegate_task` mendelegasikan pekerjaan ke agen anak dengan riwayat terisolasi, batas langkah mandiri, dan batas kedalaman rekursi maksimal 1 lapis.
- **Model Context Protocol (MCP)**: Klien stdio terintegrasi untuk menghubungkan tools pihak ketiga dari server MCP eksternal.
- **Model Router & Resilience**: Abstraksi provider LLM dengan retry eksponensial otomatis pada error transien (HTTP 429, 5xx) dan pelacakan penggunaan token per turn.
- **Security Hardening**:
  - `PathGuard`: Mencegah path traversal (escape `../`, symlink attacks, null bytes).
  - `CommandGuard`: Memvalidasi perintah shell dan memblokir binary berbahaya.
  - `SecretRedactor`: Sensor otomatis untuk API key, bot token Telegram, dan bearer token di log dan output tool.
  - `Secret Scanner`: Uji otomatis untuk memastikan tidak ada kredensial yang ter-commit ke repository.
- **Observability**: `AgentTracer` dan `TurnTelemetry` untuk pemantauan durasi eksekusi, frekuensi pemanggilan tool, dan log terpusat `~/.owibot/owibot.log`.

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

Jalankan wizard konfigurasi interaktif:

```bash
owibot setup
```

Atau setup langsung lewat flag tanpa prompt interaktif:

```bash
owibot setup \
  --api-base "http://localhost:20128/v1" \
  --api-key "local" \
  --model "ag/gemini-3.8-flash-low" \
  --token "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567" \
  --allow "123456789" \
  --yes
```

Konfigurasi disimpan di `~/.owibot/config.json`.

## Menjalankan Bot

Jalankan gateway di background:

```bash
owibot gateway
```

Cek log audit dan telemetri:

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

Menjalankan di foreground:

```bash
owibot gateway --fg
```

Autostart saat login Windows (tanpa perlu hak akses administrator):

```bash
owibot service install     # pasang shortcut di Startup
owibot service status      # cek status
owibot service uninstall   # copot autostart
```

Diagnosa sistem, model, dan konfigurasi:

```bash
owibot doctor
```

## Penggunaan di Telegram

Kirim pesan langsung ke bot. Akses dibatasi ketat hanya untuk user yang terdaftar di allowlist.

- **Rich Formatting**: Format Markdown otomatis dengan fallback aman ke plain text jika tag model tidak seimbang.
- **Tombol Aksi Cepat**: `[ 🔄 Chat Baru ]`, `[ 📊 Status ]`, dan `[ ❓ Bantuan ]`.
- **Live Progress**: Status fase kerja agen (menganalisis, menjalankan tool, memverifikasi hasil) ditampilkan secara dinamis.

### Perintah Tersedia

- `/start` - Panduan awal dan menu tombol interaktif
- `/new` - Reset konteks percakapan aktif
- `/help` - Daftar perintah bantuan

### Tools Bawaan

| Tool | Deskripsi |
|---|---|
| `read_file` | Membaca isi file di workspace |
| `write_file` | Menulis atau membuat file di workspace |
| `list_dir` | Melihat daftar file dan direktori |
| `exec` | Menjalankan perintah terminal (dengan validasi CommandGuard) |
| `web_fetch` | Mengambil konten teks dari URL |
| `update_memory` | Memperbarui catatan jangka panjang di `MEMORY.md` |
| `session_search` | Pencarian teks penuh SQLite FTS5 ke riwayat obrolan |
| `skill_view` | Membaca dokumen skill secara on-demand (*progressive disclosure*) |
| `skill_manage` | Membuat, memperbarui (*patch*), atau menghapus skill |
| `delegate_task` | Menjalankan subtask mandiri melalui subagent |
| `cron_job` | Menjadwalkan pengingat (`add`, `list`, `remove`) |
| `mcp__*` | Tools eksternal yang terhubung melalui protokol MCP |

### Format Konfigurasi (`config.json`)

Contoh file `~/.owibot/config.json` dengan dukungan server MCP:

```json
{
  "api_base": "http://localhost:20128/v1",
  "model": "ag/gemini-3.8-flash-low",
  "api_key": "local",
  "channels": {
    "telegram": {
      "token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567",
      "allow_from": ["123456789"]
    }
  },
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\PROJECT AGENT"]
    }
  }
}
```

## Struktur Proyek

```text
owibot/
├── agent/          # LifecycleEngine (understand, plan, execute, verify, recover, finalize), Memory, Skills, Tools
├── channels/       # Gateway Telegram (long-polling, status, rich text, buttons)
├── cli/            # Setup wizard, daemon manager, service installer, diagnostics
├── mcp/            # Klien dan Manager Model Context Protocol (stdio)
├── observability/  # AgentTracer, TurnTelemetry, Secret-redacting Logger
├── prompts/        # Base instruction (AGENTS.md) dan MEMORY.md
├── provider/       # ModelRouter, OpenAICompatible, Codex CLI, Token telemetry
├── scheduler/      # CronStore untuk penjadwalan berkala
└── security/       # PathGuard, CommandGuard, SecretRedactor, SecretScanner
```

## Pengujian

Jalankan suite pengujian unit dan integrasi (51 tests):

```bash
pytest
```

## Lisensi

MIT
