"""Wizard konfigurasi interaktif OwiBot."""
from __future__ import annotations

import getpass
import json
import urllib.request
from typing import Optional

TIMEOUT_SECONDS = 15

COMMON_LOCAL_ENDPOINTS = [
    ("Ollama", "http://127.0.0.1:11434/v1"),
    ("LM Studio", "http://127.0.0.1:1234/v1"),
    ("Local Port 20128", "http://localhost:20128/v1"),
]


def _http_get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def probe_models(api_base: str) -> list[str]:
    """Mengambil daftar ID model dari endpoint OpenAI-compatible."""
    try:
        data = _http_get_json(f"{api_base.rstrip('/')}/models")
        items = data.get("data", [])
        if isinstance(items, list):
            return [str(m.get("id", "")).strip() for m in items if isinstance(m, dict) and m.get("id")]
        return []
    except Exception:
        return []


def detect_local_endpoints() -> list[tuple[str, str, str]]:
    """Mendeteksi server model lokal yang sedang aktif."""
    detected: list[tuple[str, str, str]] = []
    for label, base_url in COMMON_LOCAL_ENDPOINTS:
        models = probe_models(base_url)
        for model_id in models:
            detected.append((base_url, model_id, label))
    return detected


def test_chat(api_base: str, api_key: str, model: str) -> str:
    """Uji coba completion singkat untuk memastikan koneksi ke model."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Katakan: OK"}],
        "temperature": 0,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'local'}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
    except Exception as err:
        raise RuntimeError(f"Gagal uji koneksi chat ({type(err).__name__}): {str(err)[:160]}") from err

    text = str(msg.get("content", "") or "").strip()
    return text or "(model merespons dengan tool call)"


def check_telegram(token: str) -> str:
    """Validasi bot token melalui getMe."""
    try:
        data = _http_get_json(f"https://api.telegram.org/bot{token.strip()}/getMe")
    except Exception as err:
        raise RuntimeError(f"Gagal menghubungi Telegram: {err}") from err

    if not data.get("ok"):
        raise RuntimeError(f"Telegram menolak token: {data}")
    return "@" + str(data["result"].get("username", "?"))


def parse_allowlist(raw: str) -> list[str]:
    return [p.lstrip("@").strip() for p in raw.split(",") if p.strip()]


def run_setup_flags(existing: dict, args: list[str]) -> dict:
    """Setup non-interaktif berbasis parameter baris perintah."""
    def get_arg(*flags: str, default: str = "") -> str:
        for i, a in enumerate(args):
            if a in flags and i + 1 < len(args) and not args[i + 1].startswith("--"):
                return args[i + 1]
        return default

    cfg = dict(existing)
    cfg["api_base"] = get_arg("--api-base", default=str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
    cfg["api_key"] = get_arg("--api-key", default=str(cfg.get("api_key", "local"))) or "local"
    cfg["model"] = get_arg("--model", default=str(cfg.get("model", "")))

    if not cfg["model"]:
        raise RuntimeError("Parameter --model wajib diisi (contoh: --model ag/gemini-3.8-flash-low)")

    token = get_arg("--token")
    allow = parse_allowlist(get_arg("--allow"))
    force = "--force" in args

    if token:
        try:
            bot_user = check_telegram(token)
            print(f"Telegram bot terverifikasi: {bot_user}")
        except RuntimeError as err:
            if not force:
                raise
            print(f"Peringatan: {err}")

        if not allow and not force:
            raise RuntimeError("Parameter --allow wajib diisi dengan ID Telegram pemilik bot")

        cfg["channels"] = {"telegram": {"token": token, "allow_from": allow}}

    print("Menguji koneksi model...")
    try:
        reply = test_chat(cfg["api_base"], cfg["api_key"], cfg["model"])
        print(f"Respon model: {reply[:120]}")
    except RuntimeError as err:
        if not force:
            raise
        print(f"{err} (--force aktif: melanjutkan)")

    cfg["memory"] = {"write_approval": "--mem-gate" in args}
    cfg["skills"] = {"write_approval": "--skills-gate" in args}

    if "--yes" not in args and not force:
        raise RuntimeError("Gunakan parameter --yes untuk mengonfirmasi penyimpanan konfigurasi")

    return cfg


def run_wizard(existing: dict) -> dict:
    """Wizard interaktif panduan setup."""
    from . import ui

    cfg = dict(existing)
    print(ui.banner("panduan konfigurasi"))

    print(ui.steps(1, 4, "Otak - Provider LLM"))
    pilihan_provider = ui.menu("Pilih jenis endpoint model:", [
        "Deteksi server lokal otomatis (Ollama / LM Studio)",
        "URL OpenAI-compatible kustom (misal: http://localhost:20128/v1)",
        "OpenRouter (https://openrouter.ai/api/v1)",
        "OpenAI resmi (https://api.openai.com/v1)",
    ])

    if pilihan_provider == 0:
        local_models = detect_local_endpoints()
        if not local_models:
            print(f"  {ui.yellow('Tidak ada server lokal terdeteksi.')}")
            cfg["api_base"] = ui.ask("API base URL", str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
        else:
            print(f"  {ui.green(ui.OK() + f' Ditemukan {len(local_models)} model lokal:')}")
            for i, (base, m_id, label) in enumerate(local_models[:10], start=1):
                print(f"    {ui.green(str(i) + ')')} {ui.bold(m_id)} {ui.dim(f'{label} ({base})')}")
            raw_sel = ui.ask("Pilih nomor model", "1")
            idx = int(raw_sel) - 1 if raw_sel.isdigit() and 1 <= int(raw_sel) <= min(len(local_models), 10) else 0
            cfg["api_base"], cfg["model"] = local_models[idx][:2]
    elif pilihan_provider == 1:
        cfg["api_base"] = ui.ask("API base URL", str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
    elif pilihan_provider == 2:
        cfg["api_base"] = "https://openrouter.ai/api/v1"
    else:
        cfg["api_base"] = "https://api.openai.com/v1"

    is_local_endpoint = "127.0.0.1" in cfg["api_base"] or "localhost" in cfg["api_base"]
    if is_local_endpoint:
        cfg["api_key"] = ui.ask("API Key (opsional, Enter untuk melewati)", str(cfg.get("api_key", "")) or "local") or "local"
    else:
        cfg["api_key"] = ui.ask("API Key", str(cfg.get("api_key", "")), secret=True)
        if not cfg["api_key"]:
            print(f"  {ui.yellow('Kunci kosong, melanjutkan tanpa autentikasi.')}")
            cfg["api_key"] = "local"

    if pilihan_provider != 0:
        available_models = probe_models(cfg["api_base"])
        if available_models:
            print(f"  {ui.green(ui.OK() + f' {len(available_models)} model tersedia:')}")
            for i, m_name in enumerate(available_models[:10], start=1):
                marker = ui.green("●") if m_name == cfg.get("model") else " "
                print(f"    {marker} {ui.green(str(i) + ')')} {m_name}")
            sel = ui.ask("Nomor model atau ketik nama model", str(cfg.get("model", available_models[0])))
            cfg["model"] = available_models[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(available_models[:10]) else sel
        else:
            cfg["model"] = ui.ask("Nama model", str(cfg.get("model", "")))

    print("  Menguji koneksi ke model...")
    try:
        reply = test_chat(cfg["api_base"], cfg["api_key"], cfg["model"])
        print(f"  {ui.green(ui.OK() + ' Model merespons:')} {reply[:120]}")
    except RuntimeError as err:
        print(f"  {ui.yellow(str(err))}\n  Lanjut terlebih dahulu (bisa diubah nanti).")

    print(ui.steps(2, 4, "Antarmuka - Telegram"))
    print(f"  {ui.dim('Dapatkan token bot dari @BotFather di Telegram.')}")
    while True:
        token = ui.ask("Bot Token (ketik 'skip' untuk melewati)").strip()
        if token.lower() == "skip" or not token:
            print("  Konfigurasi Telegram dilewati.")
            break
        try:
            bot_handle = check_telegram(token)
        except RuntimeError as err:
            print(f"  {ui.red(str(err))}")
            continue

        print(f"  {ui.green(ui.OK() + f' Terhubung dengan bot {ui.bold(bot_handle)}')}")
        print(f"  {ui.dim('Dapatkan User ID akun Telegram kamu dari @userinfobot.')}")
        allowed_users = parse_allowlist(ui.ask("ID Telegram yang diizinkan (koma jika lebih dari satu, atau *)"))
        if not allowed_users:
            print(f"  {ui.yellow('Allowlist wajib diisi untuk keamanan bot.')}")
            continue
        cfg["channels"] = {"telegram": {"token": token, "allow_from": allowed_users}}
        break

    print(ui.steps(3, 4, "Pengaturan Keamanan"))
    mem_approval = ui.ask("Minta konfirmasi sebelum menyimpan memori baru? [y/N]").lower() in {"y", "yes"}
    skill_approval = ui.ask("Minta konfirmasi sebelum menulis skill baru? [y/N]").lower() in {"y", "yes"}
    cfg["memory"] = {"write_approval": mem_approval}
    cfg["skills"] = {"write_approval": skill_approval}

    print(ui.steps(4, 4, "Ringkasan Konfigurasi"))
    tg_data = (cfg.get("channels") or {}).get("telegram") or {}
    print(ui.box("Rangkuman", [
        f"Model    : {cfg.get('model')}",
        f"Endpoint : {cfg.get('api_base')}",
        f"Telegram : {'Aktif' if tg_data.get('token') else 'Dilewati'}",
        f"Proteksi : memory={'Aktif' if mem_approval else 'Otomatis'}, skills={'Aktif' if skill_approval else 'Otomatis'}",
    ]))

    if ui.ask("Simpan konfigurasi ini? [Y/n]").lower() in {"", "y", "yes"}:
        return cfg
    raise RuntimeError("Konfigurasi dibatalkan oleh pengguna.")
