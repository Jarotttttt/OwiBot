"""Interactive `owibot setup` wizard (Hermes-style guided setup)."""
from __future__ import annotations

import getpass
import json
import urllib.request

TIMEOUT = 20


def _get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def probe_models(api_base: str) -> list[str]:
    """List model ids from an OpenAI-compatible endpoint. Empty on failure."""
    try:
        data = _get(f"{api_base.rstrip('/')}/models")
        ids = [str(m.get("id", "")).strip() for m in data.get("data", []) if isinstance(m, dict)]
        return [i for i in ids if i]
    except Exception:
        return []


def test_chat(api_base: str, api_key: str, model: str) -> str:
    """Tiny smoke completion. Returns reply text or raises with a short reason."""
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "temperature": 0, "stream": False}
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]
    except Exception as err:
        raise RuntimeError(f"chat test failed: {type(err).__name__}: {str(err)[:160]}")
    text = str(msg.get("content", "") or "").strip()
    if not text and msg.get("tool_calls") is None and "content" not in msg:
        raise RuntimeError("empty reply and no tool calls")
    return text or "(model replied with tool calls only - tool-calling works)"


def check_telegram(token: str) -> str:
    """Validate a bot token via getMe. Returns @username or raises."""
    try:
        data = _get(f"https://api.telegram.org/bot{token.strip()}/getMe")
    except Exception as err:
        raise RuntimeError(f"token check failed: {type(err).__name__}: {str(err)[:120]}")
    if not data.get("ok"):
        raise RuntimeError(f"Telegram rejected the token: {data}")
    return "@" + str(data["result"].get("username", "?"))


def parse_allowlist(raw: str) -> list[str]:
    return [p.lstrip("@") for p in (x.strip() for x in raw.split(",")) if p]


def run_setup_flags(existing: dict, args: list[str]) -> dict:
    """Non-interactive setup: owibot setup --api-base URL --api-key KEY --model M
    --token TOK --allow ID1,ID2 [--mem-gate] [--skills-gate] [--yes] [--force]."""
    def val(*names: str, default: str = "") -> str:
        for i, a in enumerate(args):
            if a in names and i + 1 < len(args) and not args[i + 1].startswith("--"):
                return args[i + 1]
        return default

    cfg = dict(existing)
    cfg["api_base"] = val("--api-base", default=str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
    cfg["api_key"] = val("--api-key", default=str(cfg.get("api_key", "local"))) or "local"
    cfg["model"] = val("--model", default=str(cfg.get("model", "")))
    if not cfg["model"]:
        raise RuntimeError("missing --model (e.g. --model ag/gemini-3.8-flash-low)")
    token = val("--token")
    allow = parse_allowlist(val("--allow"))
    force = "--force" in args
    if token:
        try:
            who = check_telegram(token)
        except RuntimeError as err:
            if not force:
                raise
            who = f"(unchecked: {err})"
        if not allow and not force:
            raise RuntimeError("missing --allow (your Telegram numeric ID)")
        cfg["channels"] = {"telegram": {"token": token, "allow_from": allow}}
        print(f"Telegram: {who}")
    print("Testing chat completion...")
    try:
        print(f"Model replied: {test_chat(cfg['api_base'], cfg['api_key'], cfg['model'])[:120]}")
    except RuntimeError as err:
        if not force:
            raise
        print(f"{err} (--force: continuing anyway)")
    cfg["memory"] = {"write_approval": "--mem-gate" in args}
    cfg["skills"] = {"write_approval": "--skills-gate" in args}
    if "--yes" not in args and not force:
        raise RuntimeError("add --yes to confirm saving this config")
    return cfg


def run_wizard(existing: dict) -> dict:
    """Full interactive setup with mission-control styling."""
    from . import ui
    from .cli import discover_models
    cfg = dict(existing)
    print(ui.banner("guided setup"))

    print(ui.steps(1, 4, "Otak - LLM provider"))
    prov = ui.menu("Modelnya jalan di mana?", [
        "Auto-detect lokal - Ollama / LM Studio / Codex",
        "URL OpenAI-compatible custom - mis. http://localhost:20128/v1",
        "OpenRouter - https://openrouter.ai/api/v1",
        "OpenAI - https://api.openai.com/v1",
    ])
    if prov == 0:
        found = discover_models()
        if not found:
            print(f"  {ui.yellow('tidak ada provider lokal terdeteksi.')}")
            cfg["api_base"] = ui.ask("API base URL", str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
        else:
            print(f"  {ui.green(ui.OK() + f' ketemu {len(found)} model lokal:')}")
            for i, (base, model, name) in enumerate(found[:10], start=1):
                print(f"    {ui.green(str(i) + ')')} {ui.bold(model)} {ui.dim(f'{name} · {base}')}")
            raw = ui.ask("nomor model", "1")
            idx = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= min(len(found), 10) else 0
            cfg["api_base"], cfg["model"] = found[idx][:2]
    elif prov == 1:
        cfg["api_base"] = ui.ask("API base URL", str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
    elif prov == 2:
        cfg["api_base"] = "https://openrouter.ai/api/v1"
    else:
        cfg["api_base"] = "https://api.openai.com/v1"

    local = "127.0.0.1" in cfg["api_base"] or "localhost" in cfg["api_base"]
    if local:
        cfg["api_key"] = ui.ask("API key (optional, Enter = skip)", str(cfg.get("api_key", "")) or "local") or "local"
    else:
        cfg["api_key"] = ui.ask("API key (optional untuk endpoint tanpa auth)", str(cfg.get("api_key", "")), secret=True)
        if not cfg["api_key"]:
            print(f"  {ui.yellow('key kosong - lanjut tanpa auth.')}")

    models = probe_models(cfg["api_base"])
    if models:
        print(f"  {ui.green(ui.OK() + f' {len(models)} model tersedia:')}")
        for i, m in enumerate(models[:10], start=1):
            mark = ui.green(ui.uni("●", "*")) if m == cfg.get("model") else " "
            print(f"    {mark} {ui.green(str(i) + ')')} {m}")
        raw = ui.ask("nomor model, atau ketik id model", str(cfg.get("model", models[0])))
        cfg["model"] = models[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(models[:10]) else raw
    else:
        print(f"  {ui.yellow('tidak bisa list model dari endpoint.')}")
        cfg["model"] = ui.ask("Model id", str(cfg.get("model", "")))

    print("  test chat...")
    try:
        reply = test_chat(cfg["api_base"], cfg["api_key"], cfg["model"])
        print(f"  {ui.green(ui.OK() + ' model menjawab:')} {reply[:120]}")
    except RuntimeError as err:
        print(f"  {ui.yellow(str(err))}\n  lanjut dulu - benerin nanti via setup ulang.")

    print(ui.steps(2, 4, "Kontrol - Telegram"))
    print(f"  {ui.dim('bikin bot via @BotFather (/newbot) kalau belum ada.')}")
    while True:
        token = ui.ask("Bot token (atau 'skip')").strip()
        if token.lower() == "skip" or not token:
            print("  Telegram diskip.")
            break
        try:
            who = check_telegram(token)
        except RuntimeError as err:
            print(f"  {ui.red(str(err))}")
            continue
        print(f"  {ui.green(ui.OK() + f' terhubung sebagai {ui.bold(who)}')}")
        print(f"  {ui.dim('cari ID angkamu via @userinfobot.')}")
        users = parse_allowlist(ui.ask("ID/username yang boleh pakai, koma-pisah (atau *)"))
        if not users:
            print(f"  {ui.yellow('allowlist wajib diisi untuk mengaktifkan Telegram.')}")
            continue
        cfg["channels"] = {"telegram": {"token": token, "allow_from": users}}
        break

    print(ui.steps(3, 4, "Proteksi"))
    mem_gate = ui.ask("minta persetujuan sebelum agent menyimpan memory? [y/N]").lower() in {"y", "yes"}
    skl_gate = ui.ask("minta persetujuan sebelum agent menulis skill? [y/N]").lower() in {"y", "yes"}
    cfg["memory"] = {"write_approval": mem_gate}
    cfg["skills"] = {"write_approval": skl_gate}

    print(ui.steps(4, 4, "Ringkasan"))
    tg = ((cfg.get("channels") or {}).get("telegram") or {})
    print(ui.box("siap disimpan", [
        f"model    : {cfg.get('model')}",
        f"endpoint : {cfg.get('api_base')}",
        f"telegram : {'aktif' if tg.get('token') else 'skip'}",
        f"gate     : memory={'on' if mem_gate else 'off'}, skills={'on' if skl_gate else 'off'}",
    ]))
    if ui.ask("simpan config ini? [Y/n]").lower() in {"", "y", "yes"}:
        return cfg
    raise RuntimeError("Setup dibatalkan.")


