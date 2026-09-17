# OwiBot Architecture Upgrade Roadmap: Autonomous Agent Ecosystem

Dokumen ini mendefinisikan arsitektur target, modul, dan roadmap prioritas untuk peningkatan OwiBot dari bot personal sederhana menjadi sistem autonomous agent yang modular, andal, aman, dan production-ready.

---

## 1. Arsitektur Target

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Control Plane / Gateways                           │
│     Telegram Gateway (Long-polling)    │     CLI Mission Control (Setup/Ops) │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             OwiBot Agent Core                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    Agent Loop (Plan - Execute - Verify)               │  │
│  │    • Step budget tracking   • Reflection / Self-verification          │  │
│  │    • Dynamic context builder• Recovery & fallback strategies          │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│         ┌────────────────────────────┼────────────────────────────┐         │
│         ▼                            ▼                            ▼         │
│  ┌──────────────┐             ┌──────────────┐             ┌──────────────┐  │
│  │ Model Router │             │ Tool Registry│             │ Layered Mem  │  │
│  │ & Providers  │             │ & Sandboxing │             │ & Sessions   │  │
│  └──────┬───────┘             └──────┬───────┘             └──────┬───────┘  │
│         │                            │                            │         │
└─────────┼────────────────────────────┼────────────────────────────┼─────────┘
          │                            │                            │
          ▼                            ▼                            ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│ Provider Backends│         │ Execution Engine │         │ Persistent Stores│
│ • OpenAI-compat  │         │ • Local Builtins │         │ • Curated Memory │
│ • OpenRouter     │         │ • Controlled Subs│         │ • SQLite FTS5 DB │
│ • Ollama / Local │         │ • MCP Clients    │         │ • Session History│
│ • Retry & Telemetry        │ • Security Guard │         │ • Skill Registry │
└──────────────────┘         └──────────────────┘         └──────────────────┘
```

---

## 2. Roadmap Prioritas Implementasi

### Tahap 1: Model Router & Provider Abstraction (`owibot/provider/`)
- Interface `BaseLLMProvider` dengan kontrak `chat()`, `chat_async()`.
- Implementasi `OpenAICompatibleProvider` dengan retry otomatis (exponential backoff pada 429/5xx).
- Model Router: routing berbasis peran (model utama, model fallback, model subagent murah).
- Telemetri token & latensi per turn.

### Tahap 2: Hardened Security Layer & Sandboxing (`owibot/security/`)
- `PathGuard`: mitigasi path traversal yang ketat (symlink attack, relative escape).
- `CommandGuard`: denylist destruktif + allowlist kategori perintah aman + validasi argumen.
- `SecretRedactor`: masking otomatis untuk API key, bearer token, password dari log dan pesan.

### Tahap 3: Observability & Tracing (`owibot/observability/`)
- Structured JSON & leveled logging (`owibot.log`).
- Telemetri per turn: token input/output, tool call breakdown, durasi eksekusi, status error.
- Healthcheck & diagnostic reporting (`owibot doctor` dan status Telegram).

### Tahap 4: Layered Memory System (`owibot/memory/`)
- **Lapis 1 (Long-Term Curated)**: `MEMORY.md` terstruktur dengan batas karakter, deduplikasi otomatis, dan klasifikasi kategori (fakta, preferensi, aturan).
- **Lapis 2 (Session Search FTS5)**: SQLite virtual table `turns_fts` untuk pencarian riwayat percakapan cepat dan akurat.

### Tahap 5: Self-Improving Skills Engine (`owibot/skills/`)
- Progressive disclosure: Level 0 (index nama + deskripsi ringkas), Level 1 (isi lengkap SKILL.md), Level 2 (berkas referensi).
- Validasi & linting otomatis saat skill dibuat/diperbarui.
- Tool `skill_manage` & generator skill otomatis dari task yang sukses dieksekusi.

### Tahap 6: MCP (Model Context Protocol) Client (`owibot/mcp/`)
- Klien MCP berbasis stdio (JSON-RPC 2.0).
- Konfigurasi `mcp_servers` di `config.json`.
- Registrasi tool dinamis dari MCP server langsung ke agent tool catalog.

### Tahap 7: Controlled Subagents & Advanced Loop (`owibot/agent/`)
- Tool `delegate_task`: isolasi konteks anak, pembatasan kedalaman (depth limit = 1), batas langkah mandiri.
- Siklus Plan - Execute - Verify: refleksi mandiri sebelum menyelesaikan task kompleks.

### Tahap 8: Integrasi Gateway, Pengujian Menyeluruh & Dokumentasi
- Pembaruan Telegram Gateway untuk mendukung telemetri, tombol status interaktif, dan penanganan MCP.
- Comprehensive unit & integration tests untuk semua komponen baru.
- Pembaruan dokumentasi `README.md`.
